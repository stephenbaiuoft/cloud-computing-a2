import boto3

def get_ec2_description():
    ec2 = boto3.client('ec2')
    response = ec2.describe_instances()

    ary = response['Reservations']
    dic = response['ResponseMetadata']

    for k, v in ary[0].items():
        print("key: " + str(k))
        print("value: " + str(v))

    print("******************************\n\n\n******************************\n\n\n")

    for k, v in dic.items():
        print("key: " + str(k))
        print("value: " + str(v) + "\n")


    #print(response)


if __name__ == '__main__':
    get_ec2_description()
