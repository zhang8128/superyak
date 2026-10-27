from drive import run
import sys
rc, out = run(sys.argv[1], ["init"], env_extra={"LOGNAME": "mallory", "USER": "mallory"})
print(out.splitlines()[0]); print("EXIT", rc)
