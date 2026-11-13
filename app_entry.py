"""Entry point for the optional self-contained Windows build."""
import sys
import dashboard
import kn

if __name__ == '__main__':
    if len(sys.argv)>1 and sys.argv[1]=='dashboard':
        del sys.argv[1]
        dashboard.main()
    else:
        kn.main()
