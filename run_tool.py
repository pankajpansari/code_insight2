import os
import subprocess
from dotenv import load_dotenv
from pathlib import Path
import shutil

# Default to provided example if config or rubric missing
if not os.path.exists('config.env'):
    shutil.copy('config.env.example', 'config.env')
if not os.path.exists('input/rubric.txt'):
    shutil.copy('rubric.txt.example', 'rubric.txt')

# Make output and intermediates directories
os.makedirs('output', exist_ok=True)
os.makedirs('intermediates', exist_ok=True)

load_dotenv(dotenv_path="config.env")
INPUT_DIR = os.getenv('INPUT_DIR')
# MODIFY: based on your input directory structure
INPUT_DIR = Path(INPUT_DIR) / 'all_submissions'

def main():
    # Process each folder in submissions directory
    for folder_name in os.listdir(INPUT_DIR):
        folder_path = os.path.join(INPUT_DIR, folder_name)
    
        if os.path.isdir(folder_path):
            # MODIFY: based on your input directory structure
            program_path = os.path.join(folder_path, 'shell', 'wish.c')
    
        if os.path.isfile(program_path):
            print(f"Processing: {program_path}")
            subprocess.run(['python3', 'scripts/generate_feedback.py', program_path])
        else:
            print(f"Skipping {folder_path}: program file not found")
    
    print("Processing complete!")

if __name__ == "__main__":
    main()