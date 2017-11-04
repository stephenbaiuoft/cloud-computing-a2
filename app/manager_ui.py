from flask import render_template, redirect, url_for, request, g
from app import webapp

import boto3
from app import config
from datetime import datetime, timedelta
from operator import itemgetter

import mysql.connector
from app.config import db_config


@webapp.route('/',methods=['GET'])
@webapp.route('/index',methods=['GET'])
@webapp.route('/main',methods=['GET'])
@webapp.route('/worker_list', methods=['GET'])
# Display an HTML list of all workers' instances
def main():
    # create connection to ec2 worker pool
    ec2 = boto3.resource('ec2')
    # list a list of instances named 'worker'
    workers = ec2.instances.filter(Filters=[{'Name':'tag:Name', 'Values':['worker']}])
    # {'Name':'instance-state-name', 'Values':['running']}
    cpu = []
    for instance in workers:
        cpu.append(cpu_load(instance.id)[0])

    return render_template("manager_ui.html", title="Manager UI", instances_cpu = zip(workers, cpu))


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
    return redirect(url_for('main'))


@webapp.route('/worker_list/delete_one', methods=['POST'])
# Shrink the worker pool by one
def shrink_by_one():
    ec2 = boto3.resource('ec2')
    workers = ec2.instances.filter(Filters=[{'Name':'instance-state-name', 'Values':['running']},
                                            {'Name':'tag:Name', 'Values':['worker']}])
    # check if there is any workers
    if len(workers) >= 1:
        last = workers[-1].id
        ec2.instances.filter(InstanceIds=last).terminate()
    return redirect(url_for('main'))


@webapp.route('/worker_list/delete_all', methods=['POST'])
# Delete all data in database and on S3
def delete_all():
    # delete everything on s3
    s3 = boto3.resource('s3')
    bucket = s3.Bucket('cloud-computing-photo-storage')
    response = bucket.delete_objects(
        Delete={
            'Objects': [
                {
                    'Key': '*',
                },
            ],
        },
    )
    # delete everthing in database
    cnx = get_db()
    cursor = cnx.cursor()
    query = '''
    DELETE FROM images WHERE img_id >= 1;
    DELETE FROM users WHERE user_id >= 1;
    '''
    cursor.execute(query)
    cnx.commit()

    return redirect(url_for('main'))


def cpu_load(id):

    client = boto3.client('cloudwatch')

    now = datetime.utcnow()
    past = now - timedelta(minutes=60)
    future = now + timedelta(minutes=0)

    results = client.get_metric_statistics(
        Namespace='AWS/EC2',
        MetricName='CPUUtilization',
        Dimensions=[{'Name':'InstanceId', 'Value':id}],
        StartTime=past,
        EndTime=future,
        Period=60,
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

@webapp.route('worker_list/<id>', method=['GET'])
def cpu_plot(id):
    cpu_stats = cpu_load(id)[1]
    return render_template("cpu_utilization.html", title="CPU Utilization Plot",
                           cpu_stats=cpu_stats)
