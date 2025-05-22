import subprocess

with open('usernames.txt', 'r') as f:
    for line in f: 
        username = line.strip()
        ssh_link = "git@github.com:Plaksha-Uni/shell-" + username + ".git"
        subprocess.run(["git", "clone", ssh_link], check = True)
        print(f"{ssh_link} cloned")