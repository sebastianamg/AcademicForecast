import json
import os

def load_json_data(filepath):
    """Loads data from a JSON file."""
    if not os.path.exists(filepath):
        print(f"Error: File not found at {filepath}")
        return None
    with open(filepath, 'r') as f:
        return json.load(f)

def get_curriculum(curriculum_id):
    """Loads the curriculum data."""
    filepath = os.path.join("config", f"{curriculum_id}.json")
    return load_json_data(filepath)

def is_grade_passing(grade, passing_grade, grade_order):
    """Checks if a grade is passing."""
    return grade_order.get(grade, 0) >= grade_order.get(passing_grade, 0)

def get_student_progress(student_courses, curriculum, grade_order):
    passed_courses = set()
    failed_courses = set()
    passed_choices = set()
    major_electives_passed = set()
    free_electives_passed_count = 0

    core_courses_map = {item['course']: item for item in curriculum['courses'] if 'course' in item}
    choice_map = {item['choice']['placeholder']: item for item in curriculum['courses'] if 'choice' in item}
    major_elective_options = set(curriculum.get('major_electives', {}).get('courses', []))

    for course_code, details in student_courses.items():
        grade = details.get("grade")
        pg = 'D'  # Default passing grade

        if course_code in core_courses_map:
            pg = core_courses_map[course_code].get('pg', 'D')
            if is_grade_passing(grade, pg, grade_order):
                passed_courses.add(course_code)
            else:
                failed_courses.add(course_code)
        else:
            is_major_elective = False
            if course_code in major_elective_options:
                if is_grade_passing(grade, pg, grade_order):
                    major_electives_passed.add(course_code)
                    is_major_elective = True
            
            is_choice_option = False
            for placeholder, item in choice_map.items():
                if course_code in item['choice']['courses']:
                    if is_grade_passing(grade, item.get('pg', 'D'), grade_order):
                        passed_choices.add(placeholder)
                    is_choice_option = True
                    break
            
            if not is_major_elective and not is_choice_option:
                if is_grade_passing(grade, pg, grade_order):
                    free_electives_passed_count += 1

    return passed_courses, failed_courses, passed_choices, major_electives_passed, free_electives_passed_count

def generate_forecast(student_id, student_data, course_offerings, current_year, current_semester, grade_order):
    curriculum_id = student_data.get("curriculum")
    if not curriculum_id: return {"error": "Curriculum not specified"}

    curriculum = get_curriculum(curriculum_id)
    if not curriculum: return {"error": f"Curriculum '{curriculum_id}' not found"}

    student_courses = student_data.get("courses", {})
    passed_core, failed_core, passed_choices, passed_major_electives, passed_free_electives = get_student_progress(student_courses, curriculum, grade_order)

    # --- Requirements Calculation ---
    core_map = {item['course']: item for item in curriculum['courses'] if 'course' in item}
    pending_core = {c for c, item in core_map.items() if c not in passed_core and c not in failed_core and item['semester'] >= (int(current_year.split('-')[0]) - 2023) * 2 + int(current_semester) }

    choice_map = {item['choice']['placeholder']: item for item in curriculum['courses'] if 'choice' in item}
    pending_choices = {p for p, item in choice_map.items() if p not in passed_choices and item['semester'] >= (int(current_year.split('-')[0]) - 2023) * 2 + int(current_semester)}

    major_reqs = curriculum.get('major_electives', {})
    pending_major_slots = [slot for slot in major_reqs.get('slots', []) if slot['semester'] >= (int(current_year.split('-')[0]) - 2023) * 2 + int(current_semester)]
    available_major_courses = set(major_reqs.get('courses', [])) - passed_major_electives

    pending_free_slots = [slot for slot in curriculum.get('free_electives', []) if slot['semester'] >= (int(current_year.split('-')[0]) - 2023) * 2 + int(current_semester)]

    # --- Forecasting ---
    forecast = []
    forecast_passed = set(passed_core)
    retake_courses = set(failed_core)
    year, semester = int(current_year.split('-')[0]), int(current_semester)

    for i in range(10): # Max 10 semesters
        semester_num = (year - 2023) * 2 + semester + i
        acad_year = f"{year + (i // 2)}-{year + (i // 2) + 1}"
        sem_in_year = (semester + i -1) % 2 + 1
        
        courses_to_take = []
        sem_str = str(sem_in_year)
        offering = course_offerings.get(sem_str, {})

        # Retakes
        for course in list(retake_courses):
            if course in offering: courses_to_take.append(course); retake_courses.remove(course)

        # Core
        for course in list(pending_core):
            if core_map[course]['semester'] == semester_num and set(core_map[course].get('pre', [])).issubset(forecast_passed):
                courses_to_take.append(course); pending_core.remove(course)

        # Choices
        for p_holder in list(pending_choices):
            if choice_map[p_holder]['semester'] == semester_num and set(choice_map[p_holder].get('pre', [])).issubset(forecast_passed):
                courses_to_take.append(p_holder); pending_choices.remove(p_holder)

        # Major Electives
        for slot in list(pending_major_slots):
            if slot['semester'] == semester_num:
                for course in list(available_major_courses):
                    if course in offering:
                        courses_to_take.append(course); available_major_courses.remove(course); pending_major_slots.remove(slot); break

        # Free Electives
        for slot in list(pending_free_slots):
            if slot['semester'] == semester_num: courses_to_take.append(slot['placeholder']); pending_free_slots.remove(slot)

        if courses_to_take:
            forecast.append({"academic_year": acad_year, "semester": str(sem_in_year), "courses": courses_to_take})
            forecast_passed.update(c for c in courses_to_take if c in core_map or c in available_major_courses)

    return {
        "passed_courses": sorted(list(passed_core.union(passed_major_electives, passed_choices))),
        "failed_courses_to_retake": sorted(list(failed_core)),
        "pending_core_courses": sorted(list(pending_core.union(retake_courses))),
        "pending_choice_placeholders": sorted(list(pending_choices)),
        "pending_major_electives": len(pending_major_slots),
        "pending_free_electives": len(pending_free_slots),
        "forecast": forecast
    }

def main():
    config = load_json_data("config/config.json")
    if not config: return print("Error: config.json not found or empty.")
    
    grade_order, current_year, current_semester = config.get("GRADE_ORDER"), config.get("current_year"), config.get("current_semester")
    if not all([grade_order, current_year, current_semester]): return print("Error: Incomplete configuration in config.json")

    students_data = load_json_data("students.json")
    if not students_data: return

    course_offerings = {}
    for sem in ["1s", "2s", "ss"]:
        filepath = os.path.join("config", f"{sem}.json")
        offerings = load_json_data(filepath)
        if offerings: course_offerings[sem.replace('s', '')] = offerings

    if not course_offerings: return print("Error: No course offerings found.")

    full_forecast = {student_id: generate_forecast(student_id, data, course_offerings, current_year, current_semester, grade_order) for student_id, data in students_data.items()}
    print(json.dumps(full_forecast, indent=4))

if __name__ == "__main__":
    main()
