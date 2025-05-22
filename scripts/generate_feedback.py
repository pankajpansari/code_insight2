import sys
import subprocess
from openai import OpenAI
from pydantic import BaseModel, Field
from pathlib import Path
import json
import textwrap
from dotenv import load_dotenv
import os
import datetime

# ===================== LOAD CONFIG ================================

# Load config.env file
load_dotenv(dotenv_path="../config.env")

# File paths 
PROBLEM_STATEMENT = os.getenv('PROBLEM_STATEMENT')
RUBRIC = os.getenv('RUBRIC')
INPUT_DIR = os.getenv('INPUT_DIR') 
OUTPUT_DIR = os.getenv('OUTPUT_DIR') 
INTER_DIR = os.getenv('INTER_DIR')

# LLM Models
PROPOSER_REVIEWER = os.getenv('PROPOSER_REVIEWER')
SUMMARIZER = os.getenv('SUMMARIZER')


# ===================== UTILS ====================================

# This function inserts line numbers in the original submission (like 1 | #include <stdio>)
# This makes it easier for the LLM to tell us where the annotations will be placed
def preprocess_input(input_filename):
  i = 0
  submission_program = [] 
  try:
    with open(input_filename, 'r') as f:
        for line in f:
            i += 1
            submission_program.append(str(i) + ' | ' + line)
  except FileNotFoundError:
    print(f"Error: {input_filename} not found")

  submission_program = ''.join(submission_program)
  return submission_program 

# This function calls the clang-tidy linter on the C program file and makes LLM call
# to summarize the linter output in a more readable format.
def run_linter(input_filename):

  try:
    process = subprocess.Popen(['clang-tidy', input_filename, '--', '-Wall','-std=c11'], stdout = subprocess.PIPE, stderr = subprocess.PIPE, text = True)
    linter_output, error_output = process.communicate()
    if error_output.returncode != 0:
      return f"clang-tidy exited with code {error_output.returncode}: {error_output}"

    try:
      response = client.responses.create(
          model="gpt-4.1-nano",
          input = [
              {"role": "user", "content": "The following is output from a linter. Please retain the essential points only. These will be used to guide an LLM-based automated programming feedback tool"},
              {"role": "user",
               "content": linter_output} 
          ]
      )
      return response.output_text
    except Exception as api_error:
      return f"API call error for linter output: {str(api_error)}"

  except FileNotFoundError:
    return "Error: clang-tidy not found. Please ensure it is installed and in path"
  except subprocess.SubprocessError as e:
    return f"Subprocess error: {str(e)}"
  except Exception as e:
    return f"Unexpected error: {str(e)}"

# Write number of input/cached/output tokens per API call
def write_log(response, id_str, input_filename):
  log_file = Path(INTER_DIR) / input_filename.relative_to(INPUT_DIR).parent / f"{input_filename.stem}_log.txt"

  # If file exists before first log write during this call, overwrite it
  permission = 'w' if id_str == "Proposer" else 'a'

  with open(log_file, permission) as f:
    response_dict = response.model_dump()
    cached_tokens = response_dict['usage']['input_tokens_details']['cached_tokens']
    prompt_tokens = response_dict['usage']['input_tokens']
    output_tokens = response_dict['usage']['output_tokens']
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    f.write(f"{timestamp} : {id_str} Input / Cached / Output tokens: {prompt_tokens} / {cached_tokens} / {output_tokens}\n")
 
# ========================= STUCTURED OUTPUT SCHEMA ================
# Structured output template
class Annotation(BaseModel):
  line_number: int
  category: str = Field(description="category: one of code_readability, language_convention, program_design, data_structures, pointers_memory")
  comment: str = Field(description="Detailed feedback about code at this line number")
  severity: str = Field(description="Level of importance: 'suggestion', 'issue', or 'critical'")

class Summary(BaseModel):
  strengths: str = Field(description="Description of positive aspects of the submission") 
  areas_for_improvement: str = Field(description="Description of aspects that need improvement")
  overall_assessment: str = Field(description="Brief overall evaluation of the submission")

class FeedbackResponse(BaseModel):
  annotations: list[Annotation] = Field(description="List of line-specific code feedback")
  summary: Summary = Field(description="Overall assessment of the submission")
  
# ======================================================================

client = OpenAI()

# Proposer generates a first draft of annotations 
def call_proposer(problem_statement, rubric, submission_program, input_filename):

  prompt = f"""See the following problem statement of OS assignment, the rubric for code quality feedback, and one C program submission.
  <problem_statement>
  {problem_statement}
  </problem_statement>
  
  <submission>
  {submission_program}
  </submission>

  <rubric>
  {rubric}
  </rubric>
  
  Suggest a list of annotations (comments) of feedback based on the rubric. Also give a summary. Adhere to the structured output schema.
  """

  try:
    proposer_response = client.responses.parse(
      model = PROPOSER_REVIEWER,
      input=[
        {"role": "system", "content": "Your role is to act as an OS course TA who provides qualitative feedback on student C programming assignment. Feedback is good when it is relevant for education of undergraduate computer science students, and it is not overwhelming in quantity. Please stick to the rubric."},
        {
          "role": "user",
          "content": prompt,
        },
      ],
      text_format=FeedbackResponse, 
    )
  except Exception as api_error:
    return f"API call error for proposer: {str(api_error)}"

  initial_feedback = proposer_response.output_parsed
  
  json_file = Path(INTER_DIR) / input_filename.relative_to(INPUT_DIR).parent / f"{input_filename.stem}_intermediate.json"

  with open(json_file, 'w') as f:
    json.dump(initial_feedback.model_dump(), f, indent = 4, ensure_ascii=False)
  
  write_log(proposer_response, "Proposer", input_filename)

# Reviewer reviews the feedback generated by Proposer and integrates output from clang-tidy linter
def call_reviewer(problem_statement, rubric, submission_program, input_filename):

  json_file = Path(INTER_DIR) / input_filename.relative_to(INPUT_DIR).parent / f"{input_filename.stem}_intermediate.json"

  try:
    with open(json_file, 'r') as f:
      proposer_output_data = json.load(f)
  except FileNotFoundError:
    print(f"Error: {json_file} not found")
    
  proposal_json = json.dumps(proposer_output_data)

  linter_summary = run_linter(input_filename)  
  prompt = f"""See the following problem statement of OS assignment, the rubric for code quality feedback, and one C program submission.
  <problem_statement>
  {problem_statement}
  </problem_statement>
  
  <submission>
  {submission_program}
  </submission>

  <rubric>
  {rubric}
  </rubric>
  
  Clang-tidy linter gave the following output (summary) for the submission.
  
  <linter>
  {linter_summary}
  </linter>
  
  Look at the following list of annotations and the summary of feedback. Do the following:
  1. For each annotation, check if line number is correct and if annotation is useful to give and valid
  2. Incorporate the linter output in annotations and summary, if needed.
  3. Discard annotations which are not very helpful and may clutter.
  
  <feedback>
  {proposal_json}
  </feedback>
  """
  try:
    reviewer_response = client.responses.parse(
      model = PROPOSER_REVIEWER,
      input=[
        {"role": "system", "content": "Your role is to act as an OS course TA who provides qualitative feedback on student C programming assignment. Feedback is good when it is relevant for education of undergraduate computer science students, and it is not overwhelming in quantity. Please stick to the rubric."},
        {
          "role": "user",
          "content": prompt,
        },
      ],
      text_format=FeedbackResponse, 
    )
  except Exception as api_error:
    return f"API call error for proposer: {str(api_error)}"

  refined_feedback = reviewer_response.output_parsed
  
  json_file = Path(INTER_DIR) / input_filename.relative_to(INPUT_DIR).parent / f"{input_filename.stem}_final.json"

  with open(json_file, 'w') as f:
    json.dump(refined_feedback.model_dump(), f, indent = 4, ensure_ascii=False)

  write_log(reviewer_response, "Reviewer", input_filename)
 
# This function inserts the feedback comments at the correct point in original code and appends a summary at the end
def postprocess(input_filename):

  json_file = Path(INTER_DIR) / input_filename.relative_to(INPUT_DIR).parent / f"{input_filename.stem}_final.json"

  f = open(json_file, 'r')
  x = json.load(f)
  summary = json.dumps(x['summary'])
  
  try:
    response = client.responses.create(
      model = SUMMARIZER,
      input = [
          {"role": "user", "content": "The following is summary of feedback on a C program from an automated tool. First, summarize it nicely so I can append it at the bottom of submission. Then format it properly as a C comment block; try to respect 80 character line limit convention. Do not add any suggestions of your own; give the comment block output so I can insert it as it is.\n<summary>\n" + summary + "\n</summary>"}
      ]
    )
  except Exception as api_error:
    return f"API call error for proposer: {str(api_error)}"

  write_log(response, "Summarizer", input_filename)
  
  summary = response.output_text
  
  annotation_dict = {}
  for annotation in x['annotations']:
      line_number = annotation['line_number']
      comment = annotation['comment']
      p = textwrap.wrap(comment, width = 80)
      formatted_comment = '/* \n * REVIEW: ' +  ' \n * '.join(p) + '\n */'
      annotation_dict[int(line_number)] = formatted_comment 
  
  f_input = open(input_filename, 'r')
  
  output_filename = Path(OUTPUT_DIR) / input_filename.parent.relative_to('input') / Path(input_filename.stem + '_feedback' + input_filename.suffix)

  f_output = open(output_filename, 'w')
  i = 0
  for line in f_input:
      i += 1
      if i in annotation_dict.keys():
          comment = annotation_dict[i]
          comment = "\n" + comment + "\n"
          f_output.write(comment)
      f_output.write(line) 
      
  f_output.write("\n" + summary + "\n")
  f_input.close()
  f_output.close()

def main():

  if len(sys.argv) < 2:
    print("Usage: python3 generate_feedback.py <path_to_c_file>")
    sys.exit(1)

  input_filename = Path(sys.argv[1])

  try:
    with open(PROBLEM_STATEMENT, 'r') as f:
      problem_statement = f.read()
  except FileNotFoundError:
      print(f"Error: {PROBLEM_STATEMENT} not found")
  
  try:
    with open(RUBRIC, 'r') as f:
      rubric = f.read()
  except FileNotFoundError:
    print(f"Error: {RUBRIC} not found")
  
  # Create intermediate directories in ouput/ and intermediates/ if needed
  output_path = Path(OUTPUT_DIR) / input_filename.parent.relative_to('input')
  intermediates_path = Path(INTER_DIR) / input_filename.parent.relative_to('input')
  os.makedirs(output_path, exist_ok = True)
  os.makedirs(intermediates_path, exist_ok = True)

  submission_program = preprocess_input(input_filename) 
  call_proposer(problem_statement, rubric, submission_program, input_filename)
  call_reviewer(problem_statement, rubric, submission_program, input_filename)
  postprocess(input_filename)

  print(f"Feedback generation complete for {input_filename}. Output saved.")


if __name__ == "__main__":
  main()