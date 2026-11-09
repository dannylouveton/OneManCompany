import sys

args = sys.argv[1:]
if args[:1] == ["setup-docker"]:
    from onemancompany.runner.setup import main as setup_main

    setup_main(args[1:])
else:
    from onemancompany.runner.server import main

    main(args[1:] if args[:1] == ["serve"] else args)
