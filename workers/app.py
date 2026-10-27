"""Celery transport; PostgreSQL owns job state and deduplication."""

import os

from celery import Celery

app = Celery("corpus", broker=os.environ.get("BROKER_URL"))
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
    # RabbitMQ 4.3 rejects transient non-exclusive control/event queues.
    control_queue_exclusive=True,
    event_queue_exclusive=True,
    broker_connection_timeout=3,
    broker_transport_options={"confirm_publish": True},
    task_default_queue="corpus.jobs",
    task_default_delivery_mode="persistent",
    worker_prefetch_multiplier=1,
)


@app.task(
    name="workers.validate_upload",
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=330,
    time_limit=360,
)
def validate_upload(job_id, attempt):
    from workers.validation import validate_upload as execute

    return execute(job_id, attempt)


@app.task(
    name="workers.sync_tatoeba",
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=3570,
    time_limit=3600,
)
def sync_tatoeba(run_id, attempt):
    from workers.source_sync import execute

    return execute(run_id, attempt)


@app.task(
    name="workers.build_source_index",
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=7170,
    time_limit=7200,
)
def build_source_index(run_id, attempt):
    from workers.index_build import execute

    return execute(run_id, attempt)


@app.task(
    name="workers.research",
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=3570,
    time_limit=3600,
)
def research(task_id, attempt):
    from workers.research import execute

    return execute(task_id, attempt)


@app.task(
    name="workers.import_txt",
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=1770,
    time_limit=1800,
)
def import_txt(job_id, attempt):
    from workers.materials import execute

    return execute(job_id, attempt)


@app.task(
    name="workers.export_results",
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=870,
    time_limit=900,
)
def export_results(job_id, attempt):
    from workers.exports import execute

    return execute(job_id, attempt)
