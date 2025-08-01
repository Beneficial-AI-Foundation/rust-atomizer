import time
import os
from mysql.connector import connect as mysql_connect
import subprocess

def sql2(connection, command, data):
    attempts = 0
    while attempts < 3:
        try:
            cursor = connection.cursor(dictionary=True)
            cursor.execute(command, data)
            if "UPDATE" in command or "INSERT" in command:
                connection.commit()
            return [x for x in cursor]
        except Exception as e:
            try:
                connection.reconnect(attempts=3, delay=1)
                cursor = connection.cursor(dictionary=True)
                cursor.execute(command, data)
                if "UPDATE" in command or "INSERT" in command:
                    connection.commit()
                return [x for x in cursor]
            except Exception as e:
                print(str(e))
                attempts += 1
    raise Exception("Couldn't reconnect to Mysql DB.")

def get_unatomized_repos(connection):
    cursor = connection.cursor(dictionary=True)
    cursor.execute(f"""SELECT * FROM repos 
                       WHERE 'Rust' IN (SELECT name 
                                      FROM codes JOIN languages ON codes.language_id = languages.id
                                      WHERE codes.repo_id = repos.id)
                       AND repos.status_id = 1""")
    return cursor.fetchall()

def update_rust_atomization_timestamp(connection):
    cursor = connection.cursor()
    cursor.execute("UPDATE updates SET timestamp = NOW() WHERE label = 'rust_atomization'")
    connection.commit()
    print("Updated rust_atomization timestamp.")

def load_env_file(path):
    if not os.path.exists(path):
        print(f".env file not found: {path}")
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()

def main():
    load_env_file("../.env")
    connection = mysql_connect(
        user="root",
        password=os.getenv("DB_PASSWORD"),
        host="127.0.0.1",
        database="verilib"
    )

    try:
        while True:
            repos = get_unatomized_repos(connection)
            if repos:
                print(f"Found {len(repos)} repos that are unatomized")
                for repo in repos:
                    print(f"Atomizing repo ID: {repo['id']}")
                    repo_id = str(repo['id'])
                    upload_path = f"../public/files/uploads/{repo_id}/"
                    working_dir = "/var/www/html/rust-atomizer/"

                    env = os.environ.copy()
                    env["DB_PASSWORD"] = os.getenv("DB_PASSWORD")

                    # Open pipes manually for stdout and stderr
                    process = subprocess.Popen(
                        ["./run_compose.sh", upload_path, repo_id],
                        cwd=working_dir,
                        env=env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )

                    stdout, stderr = process.communicate()

                    print("STDOUT:", stdout.decode())
                    print("STDERR:", stderr.decode())
                    
                    cursor = connection.cursor()
                    
                    query = """
                        UPDATE repos SET status_id = 2 WHERE id = %s;
                    """
                    sql2(connection, query, (repo_id,))
                    
                    connection.commit()
                    
            update_rust_atomization_timestamp(connection)
            time.sleep(5)  # Sleep 5 seconds before checking again

    except KeyboardInterrupt:
        print("Stopped by user.")
    finally:
        connection.close()

if __name__ == "__main__":
    main()
