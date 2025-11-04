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

    def _resolve_offering_for_curriculum(self, semester, curriculum_id):
        """Resolves numeric offering IDs to course codes for a specific curriculum."""
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
        """Public method to get offerings for a specific curriculum and semester."""
        return self._resolve_offering_for_curriculum(semester, curriculum_id)

    def get_all_offerings(self, semester):
        """Gets all possible course codes for a semester, for free elective selection."""
        all_courses = set()
        numeric_ids = self._offerings.get(str(semester), set())
        for num_id in numeric_ids:
            alias_entry = self._aliases.get(str(num_id))
            if alias_entry:
                for key, value in alias_entry.items():
                    if key != 'course_names' and value:
                        all_courses.update(value.split('/'))
        return all_courses

    def get_canonical_course(self, student_course_id, curriculum_id):
        """Finds the canonical course ID for a given student course ID and curriculum."""
        cache_key = f"{student_course_id}-{curriculum_id}"
        if cache_key in self._canonical_cache:
            return self._canonical_cache[cache_key]

        for alias_data in self._aliases.values():
            # Check if the student's course matches the specific curriculum alias
            if alias_data.get(curriculum_id) == student_course_id:
                self._canonical_cache[cache_key] = student_course_id
                return student_course_id
            
            # Check if it matches any part of a multi-ID curriculum alias
            curriculum_course = alias_data.get(curriculum_id, "")
            if student_course_id in curriculum_course.split('/'):
                 self._canonical_cache[cache_key] = curriculum_course
                 return curriculum_course

            # Fallback to check default aliases
            default_course = alias_data.get('default', "")
            if student_course_id in default_course.split('/'):
                # Return the version specific to the student's curriculum if it exists
                if curriculum_course:
                    self._canonical_cache[cache_key] = curriculum_course
                    return curriculum_course
                self._canonical_cache[cache_key] = default_course
                return default_course

        # If no alias found, the course ID is its own canonical ID
        self._canonical_cache[cache_key] = student_course_id
        return student_course_id

def load_json_data(filepath, is_config=False):
    """Loads data from a JSON file."""
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
    """Determines a student's progress against their curriculum."""
    passed_courses = set()
    failed_courses = set()
    passed_choices = set()
    major_electives_passed = set()
    free_electives_passed_count = 0
    curriculum_id = curriculum["curriculum_name"]

    # Build maps of all required courses from the curriculum
    core_map = {item['course']: item for item in curriculum.get('courses', []) if 'course' in item}
    choice_map = {item['choice']['placeholder']: item for item in curriculum.get('courses', []) if 'choice' in item}
    major_electives_map = {item['course']: item for item in curriculum.get('major_electives', {}).get('courses', [])}
    
    major_pg = curriculum.get('major_electives', {}).get('pg', 'D')
    free_pg = curriculum.get('free_electives', {}).get('pg', 'D')

    for student_course_id, details in student_courses.items():
        grade = details.get("grade")
        canonical_id = resolver.get_canonical_course(student_course_id, curriculum_id)

        is_accounted_for = False
        # Check against core courses
        if canonical_id in core_map:
            pg = core_map[canonical_id].get('pg', 'D')
            if is_grade_passing(grade, pg, grade_order):
                passed_courses.add(canonical_id)
            else:
                failed_courses.add(canonical_id)
            is_accounted_for = True

        # Check against major electives
        if not is_accounted_for and canonical_id in major_electives_map:
            if is_grade_passing(grade, major_pg, grade_order):
                major_electives_passed.add(canonical_id)
            is_accounted_for = True

        # Check against choice options
        if not is_accounted_for:
            for placeholder, choice_item in choice_map.items():
                choice_courses = {c['course'] for c in choice_item['choice']['courses']}
                if canonical_id in choice_courses:
                    pg = choice_item.get('pg', 'D')
                    if is_grade_passing(grade, pg, grade_order):
                        passed_choices.add(placeholder)
                    is_accounted_for = True
                    break
        
        # If not matched, it's a free elective
        if not is_accounted_for:
            if is_grade_passing(grade, free_pg, grade_order):
                free_electives_passed_count += 1

    return passed_courses, failed_courses, passed_choices, major_electives_passed, free_electives_passed_count

def is_grade_passing(grade, passing_grade, grade_order):
    """Checks if a grade is passing."""
    return grade_order.get(grade, 0) >= grade_order.get(passing_grade, 0)

def generate_forecast(student_id, student_data, grade_order, resolver, all_curricula):
    curriculum_id = student_data.get("curriculum")
    if not curriculum_id or curriculum_id not in all_curricula:
        return {"error": f"Curriculum '{curriculum_id}' not found or not loaded."}
    
    curriculum = all_curricula[curriculum_id]
    student_courses = student_data.get("courses", {})

    passed_core, failed_core, passed_choices, passed_major, passed_free_count = get_student_progress(student_courses, curriculum, grade_order, resolver)

    # --- Requirements Calculation ---
    core_map = {item['course']: item for item in curriculum.get('courses', []) if 'course' in item}
    pending_core = {c for c in core_map if c not in passed_core and c not in failed_core}

    choice_map = {item['choice']['placeholder']: item for item in curriculum.get('courses', []) if 'choice' in item}
    pending_choices = {p for p in choice_map if p not in passed_choices}

    major_reqs = curriculum.get('major_electives', {})
    pending_major_slots = len(major_reqs.get('slots', [])) - len(passed_major)

    free_reqs = curriculum.get('free_electives', {})
    pending_free_slots = len(free_reqs.get('slots', [])) - passed_free_count

    # --- Forecasting ---
    forecast = []
    forecast_passed = passed_core.union(passed_major, passed_choices)
    retake_courses = failed_core.copy()
    available_major_courses = [c for c in major_reqs.get('courses', []) if c['course'] not in passed_major]

    config = load_json_data("config/config.json")
    year, semester = int(config["current_year"].split('-')[0]), int(config["current_semester"])
    SEMESTERS_PER_YEAR = 3

    for i in range(SEMESTERS_PER_YEAR * 6): # Forecast for 6 years
        sem_in_year = ((semester - 1 + i) % SEMESTERS_PER_YEAR) + 1
        current_acad_year = f"{year + ((semester - 1 + i) // SEMESTERS_PER_YEAR)}-{year + ((semester - 1 + i) // SEMESTERS_PER_YEAR) + 1}"
        
        sem_str = str(sem_in_year) if sem_in_year != 3 else 's'
        offerings = resolver.get_offerings(sem_str, curriculum_id)
        courses_to_take = []

        current_semester_num = ((year - 2023) * SEMESTERS_PER_YEAR) + sem_in_year + (i // SEMESTERS_PER_YEAR * 2)

        # 1. Retakes
        for course in list(retake_courses):
            if course in offerings and set(core_map.get(course, {}).get('pre', [])).issubset(forecast_passed):
                courses_to_take.append(course)
                retake_courses.remove(course)

        # 2. Core & Choices
        for course in list(pending_core):
            if core_map[course]['semester'] == current_semester_num and set(core_map[course].get('pre', [])).issubset(forecast_passed) and course in offerings:
                courses_to_take.append(course)
                pending_core.remove(course)

        for p_holder in list(pending_choices):
            if choice_map[p_holder]['semester'] == current_semester_num and set(choice_map[p_holder].get('pre', [])).issubset(forecast_passed):
                courses_to_take.append(p_holder)
                pending_choices.remove(p_holder)

        # 3. Major Electives
        major_slots_this_sem = [s for s in major_reqs.get('slots', []) if s['semester'] == current_semester_num]
        for slot in major_slots_this_sem:
            if pending_major_slots > 0:
                options = [c['course'] for c in available_major_courses if set(c.get('pre', [])).issubset(forecast_passed) and c['course'] in offerings]
                if options:
                    courses_to_take.append({slot['placeholder']: options})
                    pending_major_slots -= 1
                    forecast_passed.add(slot['placeholder']) # Fulfill requirement with placeholder

        # 4. Free Electives
        free_slots_this_sem = [s for s in free_reqs.get('slots', []) if s['semester'] == current_semester_num]
        for slot in free_slots_this_sem:
            if pending_free_slots > 0:
                courses_to_take.append("free-elective")
                pending_free_slots -= 1
                forecast_passed.add(slot['placeholder']) # Fulfill requirement with placeholder

        if courses_to_take:
            forecast.append({"academic_year": current_acad_year, "semester": str(sem_in_year), "courses": courses_to_take})
            # Update forecast_passed with only concrete courses
            for item in courses_to_take:
                if isinstance(item, str) and not item.startswith("free-"):
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
    """Main function to run the academic forecast application."""
    # Load all configurations
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

    # Load all curriculum files
    curriculum_files = [f for f in os.listdir('config') if f.startswith('BScIT') and f.endswith('.json')]
    all_curricula = {f.replace('.json', ''): load_json_data(os.path.join('config', f)) for f in curriculum_files}

    # Initialize the resolver
    resolver = CourseDataResolver(aliases, offerings["1s"], offerings["2s"], offerings["ss"])

    # Generate forecast for all students
    full_forecast = { 
        student_id: generate_forecast(student_id, data, config["GRADE_ORDER"], resolver, all_curricula)
        for student_id, data in students_data.items()
    }

    print(json.dumps(full_forecast, indent=4))

if __name__ == "__main__":
    main()
