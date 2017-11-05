from flask import Flask

webapp = Flask(__name__)

from app import manager_ui
from app import refresh
# from app import auto_scaling

