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
        except Exception:
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
    cursor.execute(
        """SELECT * FROM repos 
                       WHERE 'Rust' IN (SELECT name 
                                      FROM codes JOIN languages ON codes.language_id = languages.id
                                      WHERE codes.repo_id = repos.id)
                       AND repos.status_id = 1"""
    )
    return cursor.fetchall()


def update_rust_atomization_timestamp(connection):
    cursor = connection.cursor()
    cursor.execute(
        "UPDATE updates SET timestamp = NOW() WHERE label = 'rust_atomization'"
    )
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
        database="verilib",
    )

    try:
        while True:
            connection.commit()
            repos = get_unatomized_repos(connection)
            if repos:
                print(f"Found {len(repos)} repos that are unatomized")
                for repo in repos:
                    print(f"Atomizing repo ID: {repo['id']}")
                    repo_id = str(repo["id"])
                    upload_path = f"../public/files/uploads/{repo_id}/"
                    working_dir = "/var/www/html/rust-atomizer/"

                    env = os.environ.copy()
                    env["DB_PASSWORD"] = os.getenv("DB_PASSWORD")

                    print("Removing old atoms")
                    query = """DELETE FROM atoms WHERE repo_id = %s AND statement_type != 'molecule';"""
                    sql2(connection, query, (repo_id,))

                    # print("Removing old codes")
                    # query = """DELETE FROM codes WHERE repo_id = %s;"""
                    # sql2(connection, query, (repo_id,))

                    print("Removing old snippets")
                    query = """DELETE FROM atomsnippets WHERE atom_id IN (select id from atoms where repo_id = %s);"""
                    sql2(connection, query, (repo_id,))

                    print("Removing old parent deps")
                    query = """DELETE FROM atomsdependencies WHERE parentatom_id IN (select id from atoms where repo_id = %s)"""
                    sql2(connection, query, (repo_id,))

                    print("Removing old child deps")
                    query = """DELETE FROM atomsdependencies WHERE childatom_id IN (select id from atoms where repo_id = %s)"""
                    sql2(connection, query, (repo_id,))

                    print("Running actual atomizer")
                    # Open pipes manually for stdout and stderr
                    connection.commit()
                    process = subprocess.Popen(
                        ["./run_compose.sh", upload_path, repo_id],
                        cwd=working_dir,
                        env=env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )

                    connection.commit()
                    print("Post atomizer cleanup")
                    stdout, stderr = process.communicate()

                    print("STDOUT:", stdout.decode())
                    print("STDERR:", stderr.decode())

                    print("Updating repos to atomized")
                    query = """
                        UPDATE repos SET status_id = 2 WHERE id = %s;
                    """
                    sql2(connection, query, (repo_id,))

                    print("Restoring specified status")
                    query = """
                        UPDATE atoms AS a
                        JOIN atomsbup AS b
                        ON a.full_identifier = b.full_identifier
                        AND a.identifier    = b.identifier
                        AND a.repo_id = %s
                        AND b.repo_id = %s
                        AND a.statement_type != 'molecule' 
                        AND b.statement_type != 'molecule' 
                        SET
                        a.specified = b.specified,
                        a.status_id = b.status_id;
                    """
                    sql2(
                        connection,
                        query,
                        (
                            repo_id,
                            repo_id,
                        ),
                    )

                    print("Restoring parent molecule from atom world")
                    query = """
                        UPDATE atoms AS a
                        JOIN atomsbup AS b
                        ON a.full_identifier = b.full_identifier
                        AND a.identifier = b.identifier
                        AND a.repo_id = %s
                        AND b.repo_id = %s
                        AND a.statement_type != 'molecule'
                        SET a.parent_id = b.parent_id
                        WHERE b.parent_id IN (
                            SELECT id
                            FROM (
                                SELECT id
                                FROM atoms
                                WHERE statement_type = 'molecule'
                            ) AS sub
                        );
                    """
                    sql2(
                        connection,
                        query,
                        (
                            repo_id,
                            repo_id,
                        ),
                    )

                    print("Restoring parent molecule from atom world #2")
                    query = """
                        UPDATE atoms AS a
                        JOIN atomsbup AS b
                        ON a.identifier = b.identifier
                        AND (a.full_identifier <=> b.full_identifier) 
                        AND a.repo_id = %s
                        AND b.repo_id = %s
                        LEFT JOIN atomsbup AS pb
                        ON pb.id = b.parent_id
                        AND pb.repo_id = %s
                        LEFT JOIN atoms AS p
                        ON p.identifier = pb.identifier
                        AND (p.full_identifier <=> pb.full_identifier)  
                        AND p.repo_id = a.repo_id
                        SET a.parent_id = p.id
                        WHERE a.statement_type = 'molecule'
                        AND p.id IS NOT NULL        
                        AND p.id <> a.id;          
                    """
                    sql2(
                        connection,
                        query,
                        (
                            repo_id,
                            repo_id,
                            repo_id,
                        ),
                    )

                    print("Restoring atom layouts")
                    query = """
                        UPDATE atomlayouts AS al
                        INNER JOIN atomsbup AS b
                        ON al.parent_id       = b.id
                        AND b.repo_id          = %s
                        INNER JOIN atoms AS a
                        ON a.full_identifier  = b.full_identifier
                        AND a.identifier       = b.identifier
                        AND a.repo_id          = %s
                        SET
                        al.parent_id = a.id;
                    """
                    sql2(
                        connection,
                        query,
                        (
                            repo_id,
                            repo_id,
                        ),
                    )

                    print("Removing old data")
                    query = """
                        DELETE FROM atomsbup WHERE repo_id = %s
                    """
                    sql2(connection, query, (repo_id,))

                    connection.commit()
                    print(f"Done atomizing repo ID: {repo['id']}")

            update_rust_atomization_timestamp(connection)
            time.sleep(5)  # Sleep 5 seconds before checking again

    except KeyboardInterrupt:
        print("Stopped by user.")
    except Exception as e:  # catches ValueError, OSError, MySQL errors, etc.
        print(f"Caught exception: {e}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
