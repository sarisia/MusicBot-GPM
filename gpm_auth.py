import os
import pathlib

from gmusicapi import Musicmanager

rundir = pathlib.Path(__file__).resolve().parent
gpmconf = rundir/"config"/"gpm"
credfile = gpmconf/"credential"

if not gpmconf.is_dir():
    gpmconf.mkdir(exist_ok=True)

def main():
    cli = Musicmanager(debug_logging=False)

    if credfile.is_file():
        if cli.login(oauth_credentials=str(credfile)):
            print("Login successful. Don't need to perform oauth.")
            return
        else:
            os.remove(credfile)

    cli.perform_oauth(storage_filepath=str(credfile), open_browser=True)

    if cli.login(oauth_credentials=str(credfile)):
        print("Login successful. Restart the bot!")
    else:
        print("Failed to auth. Try again later.")

if __name__ == "__main__":
    main()
    