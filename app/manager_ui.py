from flask import render_template, redirect, url_for, request, g
from app import webapp

import boto3
# import math
from app import config
from datetime import datetime, timedelta
from operator import itemgetter

import mysql.connector
from app.config import db_config

MAIN_MSG = None
CPU_THRE_H = 0.6
CPU_THRE_L = 0.1
RATIO_GROW = 2
RATIO_SHRINK = 2

@webapp.route('/',methods=['GET'])
@webapp.route('/index',methods=['GET'])
@webapp.route('/main',methods=['GET'])
@webapp.route('/worker_list', methods=['GET'])
# Display an HTML list of all workers' instances
def main():
    # create connection to ec2 worker pool
    ec2 = boto3.resource('ec2')
    # list a list of instances named 'worker'

    # workers = ec2.instances.filter(Filters=[{'Name':'tag:Name', 'Values':['worker']},
    #                                         {'Name': 'instance-state-name',
    #                                          'Values': ['running','pending','shutting-down','stopping','stopped']}
    #                                         ])

    filter_worker_tag = [{'Name': 'tag:worker', 'Values': ['vpc_worker_tag']},
                    ]
    workers = ec2.instances.filter(Filters=filter_worker_tag)
    #workers = ec2.instances.all()

    cpu = []
    for instance in workers:
        cpu.append(cpu_load(instance.id)[0])
    current_tune = [CPU_THRE_H*100, CPU_THRE_L*100, RATIO_GROW, RATIO_SHRINK]
    return render_template("manager_ui.html", title="Manager UI", instances_cpu = zip(workers, cpu), msg=MAIN_MSG, cur=current_tune)


def connect_to_database():
    return mysql.connector.connect(user=db_config['user'],
                                   password=db_config['password'],
                                   host=db_config['host'],
                                   database=db_config['database'])


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = connect_to_database()
    return db


@webapp.teardown_appcontext
def teardown_db(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


@webapp.route('/worker_list/add_one', methods=['POST'])
# Grow the worker pool by one
def grow_by_one():
    ec2 = boto3.resource('ec2')
    new_instance = ec2.create_instances(ImageId=config.ami_id,
                         MinCount=1,
                         MaxCount=1,
                         InstanceType = config.instance_type,
                         KeyName = config.key_name,
                         Monitoring = config.monitoring,
                         SecurityGroupIds = config.security_group,
                         SubnetId = config.subnet,
                         UserData = config.userdata,
                         IamInstanceProfile = config.iam_instance_profile,
                         TagSpecifications = config.tag_specification
                         )
    # attach it to load balancer
    elb = boto3.client('elb')
    response = elb.register_instances_with_load_balancer(
        LoadBalancerName = config.elbname,
        Instances = [
            {
                'InstanceId': new_instance[0].id
            }
        ]
    )
    print(response)
    global MAIN_MSG
    MAIN_MSG = 'Launched a new worker.'
    return redirect(url_for('main'))


@webapp.route('/worker_list/delete_one', methods=['POST'])
# Shrink the worker pool by one
def shrink_by_one():
    ec2 = boto3.resource('ec2')
    workers = ec2.instances.filter(Filters=[{'Name':'tag:Name', 'Values':['worker']}])
    # check if there is any workers
    if workers:
        global MAIN_MSG
        # last = workers[-1].id
        # ec2.instances.filter(InstanceIds=last).terminate()
        for worker in workers:
            if worker.state['Name'] != 'terminated':
                deleted_id = worker.id
                worker.terminate()
                # detach from load balancer
                elb = boto3.client('elb')
                response = elb.deregister_instances_from_load_balancer(
                    LoadBalancerName=config.elbname,
                    Instances=[
                        {
                            'InstanceId': deleted_id
                        },
                    ]
                )
                MAIN_MSG = 'Terminated a worker.'
                break
        else:
            MAIN_MSG = None

    return redirect(url_for('main'))


@webapp.route('/worker_list/delete_all', methods=['POST'])
# Delete all data in database and on S3
def delete_all():
    # delete everything on s3
    s3 = boto3.resource('s3')
    bucket = s3.Bucket('cloud-computing-photo-storage')
    bucket.objects.all().delete()

    # delete everthing in database
    cnx = get_db()
    cursor = cnx.cursor(buffered=True)
    query = '''DELETE FROM images WHERE img_id >= 1'''
    cursor.execute(query)
    cnx.commit()
    query = '''DELETE FROM users WHERE user_id >= 1'''
    cursor.execute(query)
    cnx.commit()

    # check if succeed
    query = '''SELECT * FROM users'''
    cursor.execute(query)
    user_data = cursor.fetchone()
    query = '''SELECT * FROM images'''
    cursor.execute(query)
    img_data = cursor.fetchone()
    bucket_data = bucket.objects.all()
    # print(user_data)
    # print(img_data)
    # print(bucket_data)
    if user_data or img_data:
        msg = 'Failed to delete all.'
    else:
        for obj in bucket_data:
            k = obj.key
            if k != '':
                msg = 'Failed to delete all.'
                break
        else:
            msg = 'Data have been deleted.'
    global MAIN_MSG
    MAIN_MSG = msg
    return redirect(url_for('main'))


def cpu_load(id):

    client = boto3.client('cloudwatch')

    now = datetime.utcnow()
    past = now - timedelta(minutes=60)
    future = now + timedelta(minutes=0)

    results = client.get_metric_statistics(
        Namespace='AWS/EC2',
        MetricName='CPUUtilization',
        Dimensions=[{'Name': 'InstanceId', 'Value': id}],
        StartTime=past,
        EndTime=future,
        Period=1 * 60,
        Statistics=['Average']
    )
    cpu_stats = []
    datapoints = results['Datapoints']
    # cpu utilization figure
    for point in datapoints:
        hour = point['Timestamp'].hour
        minute = point['Timestamp'].minute
        time = hour + minute / 60
        cpu_stats.append([time, point['Average']])
    cpu_stats = sorted(cpu_stats, key=itemgetter(0))
    # sort in timestamp order and fetch the latest one
    # in initializing phase, display 0 as cpu utilization
    if len(cpu_stats) > 0:
        last_datapoint = cpu_stats[-1][1]
        load = round((last_datapoint / 100.0), 2)
    else:
        load = 0.

    return [load, cpu_stats]

@webapp.route('/worker_list/<id>', methods=['GET'])
def cpu_plot(id):
    cpu_stats = cpu_load(id)[1]
    global MAIN_MSG
    MAIN_MSG = None
    return render_template("cpu_utilization.html", title="CPU Utilization Plot",
                           cpu_stats=cpu_stats)


@webapp.route('/worker_list/tune', methods=['POST'])
def tune():
    global CPU_THRE_L, CPU_THRE_H, RATIO_GROW, RATIO_SHRINK, MAIN_MSG
    new_thre_l = request.form.get('thre_l', "")
    new_thre_h = request.form.get('thre_h', "")
    new_ratio_grow = request.form.get('ratio_grow', "")
    new_ratio_shrink = request.form.get('ratio_shrink', "")
    if new_thre_l != "" and new_thre_h != "":
        new_thre_l = float(new_thre_l) / 100.
        new_thre_h = float(new_thre_h) / 100.
        if 0. <= new_thre_l < new_thre_h <= 1.:
            CPU_THRE_L = new_thre_l
            CPU_THRE_H = new_thre_h
    elif new_thre_l == "" and new_thre_h != "":
        new_thre_h = float(new_thre_h) / 100.
        if 1 >= new_thre_h > CPU_THRE_L:
            CPU_THRE_H = new_thre_h
    elif new_thre_h == "" and new_thre_l != "":
        new_thre_l = float(new_thre_l) / 100.
        if 0 <= new_thre_l < CPU_THRE_H:
            CPU_THRE_L = new_thre_l

    if new_ratio_grow != "":
        new_ratio_grow = float(new_ratio_grow)
        if new_ratio_grow >= 1.:
            RATIO_GROW = new_ratio_grow
    if new_ratio_shrink != "":
        new_ratio_shrink = float(new_ratio_shrink)
        if new_ratio_shrink >= 1.:
            RATIO_SHRINK = new_ratio_shrink
    MAIN_MSG = 'CPU_THRESHOLD_HIGH: '+str(CPU_THRE_H)+', CPU_THRESHOLD_LOW: '+str(CPU_THRE_L)+', RATIO_GROW: '\
               +str(RATIO_GROW)+', RATIO_SHRINK: '+str(RATIO_SHRINK)

    return redirect(url_for('main'))


def get_parameters():
    return [CPU_THRE_H, CPU_THRE_L, RATIO_GROW, RATIO_SHRINK]