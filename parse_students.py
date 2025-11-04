#!/usr/bin/python3
import json
import sys
from collections import defaultdict

def restructure_student_data(input_path, output_path):
    """
    Reads a flat list of student course records, restructures it by grouping
    courses under each student ID, and writes the result to a new JSON file.
    """
    try:
        with open(input_path, 'r') as f:
            flat_data = json.load(f)
    except FileNotFoundError:
        print(f"Error: Input file not found at '{input_path}'")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from '{input_path}'. Please ensure it's a valid JSON file.")
        sys.exit(1)

    # Using defaultdict to simplify the creation of new student entries
    restructured_data = defaultdict(lambda: {"curriculum": "", "courses": {}})

    for record in flat_data:
        student_id = record.get('student_id')
        curriculum = record.get('curriculum')
        course_id = record.get('course_id')

        # Skip any record that is missing essential information
        if not all([student_id, curriculum, course_id]):
            print(f"Skipping record with missing data: {record}")
            continue

        # Assign the curriculum for the student (will only be set once per student)
        if not restructured_data[student_id]['curriculum']:
            restructured_data[student_id]['curriculum'] = curriculum

        # Create the nested course entry
        course_details = {
            'year': record.get('year'),
            'semester': record.get('semester'),
            'grade': record.get('grade'),
            'internal_course_id': record.get('internal_course_id')
        }
        
        # Add the course to the student's record
        restructured_data[student_id]['courses'][course_id] = course_details

    # Write the newly structured data to the output file
    with open(output_path, 'w') as f:
        json.dump(restructured_data, f, indent=4)

    print(f"Successfully restructured data and saved it to '{output_path}'")

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: python parse_students.py <input_file> <output_file>")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    
    restructure_student_data(input_file, output_file)