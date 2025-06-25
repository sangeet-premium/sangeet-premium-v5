# celery_app.py

from celery import Celery

# The first argument is the name of the app, which should be the project's module name.
# The `broker` and `backend` arguments specify the connection URLs for your message broker
# and result backend. We're using Redis for both.
celery = Celery(
    'sangeet_download_server',
    broker='redis://redis-celery:6379/0',
    backend='redis://redis-celery:6379/0',
    include=['tasks']  # List of modules to import when a worker starts.
)

# Optional Celery configuration
celery.conf.update(
    result_expires=3600,  # Expire results after 1 hour.
    task_track_started=True,
)

if __name__ == '__main__':
    celery.start()