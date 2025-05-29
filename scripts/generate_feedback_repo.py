import subprocess
from pathlib import Path
from unidiff import PatchSet
import os
import sys
from openai import OpenAI
from pydantic import BaseModel, Field
import json
import textwrap
from dotenv import load_dotenv
import datetime
import argparse

THRESHOLD = 10

# Load config.env file
load_dotenv(dotenv_path="config_repo.env")

# File paths 
PROBLEM_STATEMENT = os.getenv('PROBLEM_STATEMENT')
RUBRIC = os.getenv('RUBRIC')
INPUT_DIR = os.getenv('INPUT_DIR') 
OUTPUT_DIR = os.getenv('OUTPUT_DIR') 
INTER_DIR = os.getenv('INTER_DIR')

# LLM Models
PROPOSER_REVIEWER = os.getenv('PROPOSER_REVIEWER')

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

class FeedbackResponse(BaseModel):
  annotations: list[Annotation] = Field(description="List of line-specific code feedback")

# ======================================================================
client = OpenAI()


# Proposer generates a first draft of annotations 
def call_proposer(problem_statement, rubric, submission_program, input_filename):

  prompt = f"""For an OS assignment on xv6 OS, the student has made modifications to the xv6 repo in repose to following problem statement. Here is one file from the repo that has been modified with the added lines prepended by + symbol. Note that this is only a part of the solution of the assignment. 

  <problem_statement>
  {problem_statement}
  </problem_statement>
  
  <submission>
  {submission_program}
  </submission>

  <rubric>
  {rubric}
  </rubric>
  
  Suggest a list of annotations (comments) of feedback based on the rubric. Adhere to the structured output schema. Give feedback on the modified lines. It's okay to not give any feedback if there's is not a strong need for one.
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

  prompt = f"""For an OS assignment on xv6 OS, the student has made modifications to the xv6 repo in repose to following problem statement. Here is one file from the repo that has been modified with the added lines prepended by + symbol. Note that this is only a part of the solution of the assignment. 

  <problem_statement>
  {problem_statement}
  </problem_statement>
  
  <submission>
  {submission_program}
  </submission>

  <rubric>
  {rubric}
  </rubric>
 
  Look at the following list of annotations and the summary of feedback. Do the following:
  1. For each annotation, check if line number is correct and if annotation is useful to give and valid
  2. Discard annotations which are not very helpful and may clutter.
  
  <feedback>
  {proposal_json}
  </feedback>
  """
  try:
    reviewer_response = client.responses.parse(
      model = PROPOSER_REVIEWER,
      input=[
        {"role": "system", "content": "Your role is to act as an OS course TA who provides qualitative feedback on student C programming assignment. Feedback is good when it is relevant for education of undergraduate computer science students, and it is not overwhelming in quantity. Please stick to the rubric. Specifically, your role is to act as a reviewer of feedback comments proposed by a Proposer LLM."},
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


def postprocess(input_filename):

  json_file = Path(INTER_DIR) / input_filename.relative_to(INPUT_DIR).parent / f"{input_filename.stem}_final.json"

  f = open(json_file, 'r')
  x = json.load(f)
  
  # If there are no annotations, skip writing to output file
  if len(x['annotations']) == 0:
     return

  annotation_dict = {}
  for annotation in x['annotations']:
      line_number = annotation['line_number']
      comment = annotation['comment']
      p = textwrap.wrap(comment, width = 80)
      formatted_comment = '/* \n * REVIEW: ' +  ' \n * '.join(p) + '\n */'
      annotation_dict[int(line_number)] = formatted_comment 
  
  f_input = open(input_filename, 'r')
  
  output_filename = Path(OUTPUT_DIR) / input_filename.parent.relative_to(INPUT_DIR) / Path('feedback.c')

  f_output = open(output_filename, 'a')
  i = 0
  f_output.write(f'\n/*============================{input_filename.name}=========================================/*\n')
  for line in f_input:
      i += 1
      if i in annotation_dict.keys():
          comment = annotation_dict[i]
          comment = "\n" + comment + "\n"
          f_output.write(comment)
          f_output.write(f"line {i}: {line[2:]}") 
      
  f_input.close()
  f_output.close()

def generate_file_feedback(input_filename):

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
  
  # Create intermediate directories in output/ and intermediates/ if needed
  output_path = Path(OUTPUT_DIR) / input_filename.parent.relative_to(INTER_DIR)
  os.makedirs(output_path, exist_ok = True)

  submission_program = preprocess_input(input_filename) 
  call_proposer(problem_statement, rubric, submission_program, input_filename)
  call_reviewer(problem_statement, rubric, submission_program, input_filename)
  
  postprocess(input_filename)

  print(f"Feedback generation complete for {input_filename}. Output saved.")

def main():

    print(INTER_DIR)
    parser = argparse.ArgumentParser()
    parser.add_argument("source_repo_path", help = "Path of original repo (source)")
    parser.add_argument("target_repo_path", help = "Path of modified repo (target)")
    args = parser.parse_args()
    source_repo = Path(args.source_repo_path)
    target_repo = Path(args.target_repo_path)

    process = subprocess.Popen(['diff', '-r', '-u', source_repo, target_repo], stdout = subprocess.PIPE, stderr = subprocess.PIPE, text = True)
    diff_out, diff_err = process.communicate()
    os.makedirs(Path(INTER_DIR) / target_repo.parent.relative_to('input'), exist_ok=True)
    diff_filename = Path(INTER_DIR) / target_repo.relative_to('input') / 'repo.diff'
    with open(diff_filename, 'w') as f:
        f.write(diff_out)

    """
    # Generate feedback for new files (files only in target_repo) 
    target_str = 'Only in ' + str(target_repo)
    with open(diff_filename, 'r') as f:
      for line in f:
        if target_str in line:
          filename = line.split()[-1]
          if filename.endswith('.c'):
            input_filename = target_repo / filename
            # output here means processed version of input program file; prepend + to all added lines in program file
            # in this case, all lines are prepended with +
            output_filename = Path(INTER_DIR) / input_filename.parent.relative_to('input') / f"{input_filename.name}"
            f_input = open(input_filename, 'r')
            f_output = open(output_filename, 'w')
            for line in f_input:
              f_output.write('+ ' + line)

            f_input.close()
            f_output.close() 

            generate_file_feedback(output_filename)
    """
      # Generate feedback for modified files
    patch = PatchSet.from_filename(diff_filename)
    for p in patch:
        if Path(p.source_file).suffix == '.c':
            input_filename = Path(p.target_file)
            hunk_set = set() 

            for hunk in p:
                for i in range(hunk.target_length):
                    hunk_set.add(hunk.target_start + i)

            if len(hunk_set) < THRESHOLD:
                continue
            f_input = open(input_filename, 'r')
            output_filename = Path(INTER_DIR) / input_filename.parent.relative_to('input') / f"{input_filename.name}"

            f_output = open(output_filename, 'w')
            i = 0
            for line in f_input:
                i += 1
                if i in hunk_set: 
                    f_output.write('+ ' + line)
                else:
                    f_output.write(line) 
            
            f_input.close()
            f_output.close()
            generate_file_feedback(output_filename)

if __name__ == "__main__":
   main()