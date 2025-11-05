#!/usr/bin/python3
import json
import os
import sys
from collections import defaultdict

class CourseDataResolver:
    """Handles the complex logic of resolving course IDs, aliases, and offerings."""

    def __init__(self, aliases, offerings_1s, offerings_2s, offerings_ss):
        self._aliases = aliases
        self._offerings = {
            '1': set(offerings_1s),
            '2': set(offerings_2s),
            's': set(offerings_ss)
        }
        self._offering_cache = {}
        self._canonical_cache = {}
        self._course_id_to_details = {}
        self._course_id_to_internal_code = {}

        # Pre-build a reverse map for efficient detail lookups
        for internal_code, alias_data in aliases.items():
            course_name = alias_data.get('course_names', 'N/A')
            for key, course_id_str in alias_data.items():
                if key == 'course_names' or not course_id_str:
                    continue
                for course_id in course_id_str.split('/'):
                    if course_id not in self._course_id_to_details:
                        self._course_id_to_details[course_id] = {
                            "internal_code": internal_code,
                            "name": course_name
                        }
                    self._course_id_to_internal_code[course_id] = internal_code

    def get_course_details(self, course_id, curriculum_id):
        """Returns a detailed object for a given course ID."""
        details = self._course_id_to_details.get(course_id)
        if details:
            return {
                "name": details['name'],
                "internal_code": details['internal_code'],
                "course_id": course_id
            }
        # Fallback for placeholders or courses not in aliases.json
        return course_id

    def get_internal_code(self, course_id):
        """Returns the internal code for a given course ID."""
        return self._course_id_to_internal_code.get(course_id)

    def _resolve_offering_for_curriculum(self, semester, curriculum_id):
        offering_key = f"{semester}-{curriculum_id}"
        if offering_key in self._offering_cache:
            return self._offering_cache[offering_key]

        resolved_courses = set()
        numeric_ids = self._offerings.get(str(semester), set())
        for num_id in numeric_ids:
            alias_entry = self._aliases.get(str(num_id))
            if alias_entry:
                course_code = alias_entry.get(curriculum_id) or alias_entry.get('default')
                if course_code:
                    resolved_courses.update(course_code.split('/'))
        
        self._offering_cache[offering_key] = resolved_courses
        return resolved_courses

    def get_offerings(self, semester, curriculum_id):
        return self._resolve_offering_for_curriculum(semester, curriculum_id)

    def get_canonical_course(self, student_course_id, curriculum_id):
        cache_key = f"{student_course_id}-{curriculum_id}"
        if cache_key in self._canonical_cache:
            return self._canonical_cache[cache_key]

        for alias_data in self._aliases.values():
            curriculum_course = alias_data.get(curriculum_id, "")
            if student_course_id in curriculum_course.split('/'):
                 self._canonical_cache[cache_key] = curriculum_course
                 return curriculum_course

            default_course = alias_data.get('default', "")
            if student_course_id in default_course.split('/'):
                result = curriculum_course if curriculum_course else default_course
                self._canonical_cache[cache_key] = result
                return result

        self._canonical_cache[cache_key] = student_course_id
        return student_course_id

def load_json_data(filepath):
    if not os.path.exists(filepath):
        print(f"Error: File not found at {filepath}", file=sys.stderr)
        return None
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from {filepath}", file=sys.stderr)
        return None

def get_student_progress(student_courses, curriculum, grade_order, resolver):
    passed_courses, failed_courses, passed_choices, major_electives_passed = set(), set(), set(), set()
    free_electives_passed_count = 0
    curriculum_id = curriculum["curriculum_name"]
    passed_internal_codes = set()

    core_map = {item['course']: item for item in curriculum.get('courses', []) if 'course' in item}
    choice_map = {item['choice']['placeholder']: item for item in curriculum.get('courses', []) if 'choice' in item}
    major_electives_map = {item['course']: item for item in curriculum.get('major_electives', {}).get('courses', [])}
    
    major_pg = curriculum.get('major_electives', {}).get('pg', 'D')
    free_pg = curriculum.get('free_electives', {}).get('pg', 'D')

    for student_course_id, details in student_courses.items():
        grade = details.get("grade")
        internal_code = resolver.get_internal_code(student_course_id)
        if internal_code and is_grade_passing(grade, 'D', grade_order):
            passed_internal_codes.add(internal_code)

        canonical_id = resolver.get_canonical_course(student_course_id, curriculum_id)
        is_accounted_for = False

        if canonical_id in core_map:
            pg = core_map[canonical_id].get('pg', 'D')
            (passed_courses if is_grade_passing(grade, pg, grade_order) else failed_courses).add(canonical_id)
            is_accounted_for = True

        if not is_accounted_for and canonical_id in major_electives_map:
            if is_grade_passing(grade, major_pg, grade_order):
                major_electives_passed.add(canonical_id)
            is_accounted_for = True

        if not is_accounted_for:
            for placeholder, choice_item in choice_map.items():
                choice_courses = {c['course'] for c in choice_item['choice']['courses']}
                if canonical_id in choice_courses:
                    pg = choice_item.get('pg', 'D')
                    if is_grade_passing(grade, pg, grade_order):
                        passed_choices.add(placeholder)
                    is_accounted_for = True
                    break
        
    return passed_courses, failed_courses, passed_choices, major_electives_passed, free_electives_passed_count, passed_internal_codes

def is_grade_passing(grade, passing_grade, grade_order):
    return grade_order.get(grade, 0) >= grade_order.get(passing_grade, 0)

def generate_forecast(student_id, student_data, grade_order, resolver, all_curricula):
    curriculum_id = student_data.get("curriculum")
    if not curriculum_id or curriculum_id not in all_curricula:
        return {"error": f"Curriculum '{curriculum_id}' not found or not loaded."}
    
    curriculum = all_curricula[curriculum_id]
    passed_core, failed_core, passed_choices, passed_major, passed_free_count, passed_internal_codes = get_student_progress(
        student_data.get("courses", {}), curriculum, grade_order, resolver
    )

    core_map = {item['course']: item for item in curriculum.get('courses', []) if 'course' in item}
    pending_core = {c for c in core_map if c not in passed_core and c not in failed_core}

    choice_map = {item['choice']['placeholder']: item for item in curriculum.get('courses', []) if 'choice' in item}
    pending_choices = {p for p in choice_map if p not in passed_choices}

    major_reqs = curriculum.get('major_electives', {})
    pending_major_slots = len(major_reqs.get('slots', [])) - len(passed_major)

    free_reqs = curriculum.get('free_electives', {})
    pending_free_slots = len(free_reqs.get('slots', [])) - passed_free_count

    forecast, forecast_passed = [], passed_core.union(passed_major, passed_choices)
    retake_courses = failed_core.copy()
    available_major_courses = [c for c in major_reqs.get('courses', []) if c['course'] not in passed_major]
    
    forecasted_internal_codes = set()

    config = load_json_data("config/config.json")
    year, semester = int(config["current_year"].split('-')[0]), int(config["current_semester"])
    SEMESTERS_PER_YEAR = 3

    for i in range(SEMESTERS_PER_YEAR * 6):
        sem_in_year = ((semester - 1 + i) % SEMESTERS_PER_YEAR) + 1
        current_acad_year = f"{year + ((semester - 1 + i) // SEMESTERS_PER_YEAR)}-{year + ((semester - 1 + i) // SEMESTERS_PER_YEAR) + 1}"
        sem_str = str(sem_in_year) if sem_in_year != 3 else 's'
        offerings = resolver.get_offerings(sem_str, curriculum_id)
        courses_to_take = []

        current_semester_num = ((year - 2023) * SEMESTERS_PER_YEAR) + sem_in_year + (i // SEMESTERS_PER_YEAR * 2)

        for course in list(retake_courses):
            internal_code = resolver.get_internal_code(course)
            if course in offerings and set(core_map.get(course, {}).get('pre', [])).issubset(forecast_passed) and internal_code not in passed_internal_codes and internal_code not in forecasted_internal_codes:
                courses_to_take.append(resolver.get_course_details(course, curriculum_id))
                retake_courses.remove(course)
                forecasted_internal_codes.add(internal_code)

        for course in list(pending_core):
            internal_code = resolver.get_internal_code(course)
            if core_map[course]['semester'] == current_semester_num and set(core_map[course].get('pre', [])).issubset(forecast_passed) and course in offerings and internal_code not in passed_internal_codes and internal_code not in forecasted_internal_codes:
                courses_to_take.append(resolver.get_course_details(course, curriculum_id))
                pending_core.remove(course)
                forecasted_internal_codes.add(internal_code)

        for p_holder in list(pending_choices):
            if choice_map[p_holder]['semester'] == current_semester_num and set(choice_map[p_holder].get('pre', [])).issubset(forecast_passed):
                courses_to_take.append(p_holder)
                pending_choices.remove(p_holder)

        major_slots_this_sem = [s for s in major_reqs.get('slots', []) if s['semester'] == current_semester_num]
        for slot in major_slots_this_sem:
            if pending_major_slots > 0:
                options = []
                internal_codes_in_options = set()
                for c in available_major_courses:
                    internal_code = resolver.get_internal_code(c['course'])
                    if set(c.get('pre', [])).issubset(forecast_passed) and c['course'] in offerings and internal_code not in passed_internal_codes and internal_code not in forecasted_internal_codes and internal_code not in internal_codes_in_options:
                        options.append(resolver.get_course_details(c['course'], curriculum_id))
                        internal_codes_in_options.add(internal_code)
                if options:
                    courses_to_take.append({slot['placeholder']: options})
                    pending_major_slots -= 1
                    forecast_passed.add(slot['placeholder'])

        free_slots_this_sem = [s for s in free_reqs.get('slots', []) if s['semester'] == current_semester_num]
        for slot in free_slots_this_sem:
            if pending_free_slots > 0:
                courses_to_take.append("free-elective")
                pending_free_slots -= 1
                forecast_passed.add(slot['placeholder'])

        if courses_to_take:
            forecast.append({"academic_year": current_acad_year, "semester": str(sem_in_year), "courses": courses_to_take})
            for item in courses_to_take:
                if isinstance(item, dict) and item.get("course_id"):
                    forecast_passed.add(item["course_id"])
                elif isinstance(item, str):
                     forecast_passed.add(item)

    return {
        "passed_courses": sorted(list(passed_core.union(passed_major, passed_choices))),
        "failed_courses_to_retake": sorted(list(failed_core)),
        "pending_core_courses": sorted(list(pending_core.union(retake_courses))),
        "pending_choice_placeholders": sorted(list(pending_choices)),
        "pending_major_electives": pending_major_slots,
        "pending_free_electives": pending_free_slots,
        "forecast": forecast
    }

def main():
    config = load_json_data("config/config.json")
    if not config: sys.exit(1)

    aliases = load_json_data("config/aliases.json")
    if not aliases: sys.exit(1)

    students_data = load_json_data("students.json")
    if not students_data: sys.exit(1)

    offerings = {s: load_json_data(f"config/{s}.json") for s in ["1s", "2s", "ss"]}
    if not all(offerings.values()):
        print("Error: One or more course offering files are missing or empty.", file=sys.stderr)
        sys.exit(1)

    curriculum_files = [f for f in os.listdir('config') if f.startswith('BScIT') and f.endswith('.json')]
    all_curricula = {f.replace('.json', ''): load_json_data(os.path.join('config', f)) for f in curriculum_files}

    resolver = CourseDataResolver(aliases, offerings["1s"], offerings["2s"], offerings["ss"])

    full_forecast = { 
        student_id: generate_forecast(student_id, data, config["GRADE_ORDER"], resolver, all_curricula)
        for student_id, data in students_data.items()
    }

    print(json.dumps(full_forecast, indent=4))

if __name__ == "__main__":
    main()
