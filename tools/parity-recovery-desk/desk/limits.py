"""Separate process: apply POSIX resource bounds before exec (safe with server threads)."""
import os
import resource
import sys
resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024**2, 1024 * 1024**2))
resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024**2, 64 * 1024**2))
resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
os.execv(sys.argv[1], sys.argv[1:])
