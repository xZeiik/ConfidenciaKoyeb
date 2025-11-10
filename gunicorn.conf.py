import multiprocessing
import os

# Binding
bind = "0.0.0.0:8000"

# Workers
workers = 4
max_requests = 1000
max_requests_jitter = 50

# Timeout
timeout = 600
graceful_timeout = 30
keepalive = 5

# Logging
errorlog = "-"
accesslog = "-"
loglevel = "info"

# Security
forwarded_allow_ips = "*"

# Process naming
proc_name = "bufete"

# Server mechanics
daemon = False
worker_class = "sync"
worker_connections = 1000