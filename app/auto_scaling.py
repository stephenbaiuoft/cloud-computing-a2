# import atexit
#
# from apscheduler.schedulers.background import BackgroundScheduler
# from apscheduler.triggers.interval import IntervalTrigger
#
# from app import manager_ui
#
# scheduler = BackgroundScheduler()
# scheduler.start()
# scheduler.add_job(
#     func=manager_ui.main,
#     trigger=IntervalTrigger(seconds=60),
#     id='worker_list',
#     name='Refresh the worker pool every 60 seconds',
#     replace_existing=True)
# # Shut down the scheduler when exiting the app
# atexit.register(lambda: scheduler.shutdown())
#
