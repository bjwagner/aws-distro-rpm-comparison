#!/usr/bin/python
"""Create EC2 instances with different Linux distros and compare
the available RPMs on them.

Usage:
  aws-distro-rpm-comparions.py [options] VPC_ID USER@AMI_ID...

Arguments:
  VPC_ID        VPC_ID to use
  USER@AMI_ID   AMI IDs to use with their respective SSH user

Options:
  -h --help            show this help message and exit
  --version            show version and exit
  --region=REGION      use this region [default: eu-west-1]
  --type=TYPE          EC2 instance type [default: t2.micro]
  --defaultuser=USER   Default user to use for USER@AMI_ID [default: ec2-user]
  --verbose            Verbose logging
  --debug              Debug logging

Notes:

* The AMI_IDs and the EC2 instance type must match (HVM or PV)

"""
from __future__ import print_function

from docopt import docopt
import boto, boto.ec2, boto.vpc
import os, platform, time
import atexit
from pprint import pprint
import logging

from fabric.api import env, run, sudo, execute, parallel

logger = logging.getLogger(__name__)


class Environment(object):
    wait_delay_in_seconds = 10

    def decommission(self):
        logger.info("Removing Environment")

        try:
            if self.instances:
                instance_ids = [i.id for i in self.instances]
                logger.info("Terminating Instances {0}".format(", ".join(instance_ids)))
                self.conn.terminate_instances(instance_ids)
                self.wait_for_instances(target_state="terminated")
        except Exception as e:
            logger.exception(e)

        try:
            if self.securitygroup.delete():
                logger.info("Deleted Security Group")
        except AttributeError:
            pass

        try:
            if self.keypair.delete():
                logger.info("Deleted Key Pair")
        except AttributeError:
            pass


    def __init__(self, region, vpc_id):
        atexit.register(self.decommission)
        try:
            self.conn = boto.ec2.connect_to_region(region)
            self.vpc_id = vpc_id
            self.myid = os.environ["USER"] + "_" + platform.node()
            self.keypair = self.conn.create_key_pair(self.myid)
            logger.info("Created Key Pair {0}".format(self.keypair.name))
            self.securitygroup = self.conn.create_security_group(name=self.myid,
                                                                 description='Temporary Security Group',
                                                                 vpc_id=self.vpc_id)
            logger.info("Created Security Group {0}".format(self.securitygroup.id))
            self.securitygroup.authorize('tcp', 22, 22, '0.0.0.0/0')
            self.first_subnet = boto.vpc.connect_to_region(region).get_all_subnets()[0]
            self.instances = []  # will be list of Instance
        except boto.exception.EC2ResponseError as e:
            raise Exception("BOTO Error: {0.reason}\n{0.body}".format(e))


    def run_instances(self, ami_id, user, instance_type):
        instances = self.conn.run_instances(ami_id,
                                            security_group_ids=[self.securitygroup.id],
                                            instance_type=instance_type,
                                            subnet_id=self.first_subnet.id,
                                            key_name=self.keypair.name).instances
        time.sleep(1)  # give AWS some time to collect its wits before calling add_tag
        for instance in instances:
            instance.add_tag("Name", __file__)
            logger.info("Created Instance {id} for {image_id}".format(**vars(instance)))
            instance_object = Instance(instance_object=instance,
                                       image_object=self.conn.get_image(instance.image_id),
                                       user=user)
            self.instances.append(instance_object)

    def wait_for_instances(self, target_state, timeout_in_seconds=300):
        """Wait till all instances reach the given state.
        NOTE: This method only waits, you still have to trigger the change yourself.

        :param target_state: State that the instances in the environment should have, e.g. terminated or running
        :param timeout_in_seconds: how long to wait for ALL instances having this state, default 120 seconds
        :return: True or False
        """
        end_time = time.time() + timeout_in_seconds
        wrong_state_instances = list(self.instances)
        logger.info(
            "Waiting {0} seconds for {1} instances to be {2}".format(timeout_in_seconds,
                                                                     len(wrong_state_instances),
                                                                     target_state))
        while time.time() <= end_time:
            for i in wrong_state_instances:
                i.update()
            wrong_state_instances = [i for i in wrong_state_instances if i.state != target_state]
            if wrong_state_instances:
                logger.info("The following instances still have the wrong state: {0}".format(
                    ", ".join([i.id + " " + i.state for i in wrong_state_instances])))
                time.sleep(self.wait_delay_in_seconds)
            else:
                return True
        raise Exception(
            "Could not reach {0} state after waiting {1} seconds".format(target_state, timeout_in_seconds))


class Instance(object):
    def __init__(self, instance_object, image_object, user):
        self.instance = instance_object
        self.image_id = instance_object.image_id
        self.image_name = image_object.name
        self.image_description = image_object.description
        self.id = instance_object.id
        self.user = user

    def update(self):
        self.instance.update()

    @property
    def state(self):
        return self.instance.state

    @property
    def ip_address(self):
        return self.instance.ip_address


def run_main(aws_region, instance_type, vpc_id, user_at_ami_id_list, default_user):
    environment = Environment(region=aws_region, vpc_id=vpc_id)

    for user_at_ami_id in user_at_ami_id_list:
        user_and_ami_id = user_at_ami_id.split("@")
        if len(user_and_ami_id) == 2:
            user = user_and_ami_id[0]
            ami_id = user_and_ami_id[1]
        else:
            user = default_user
            ami_id = user_and_ami_id[0]
        environment.run_instances(ami_id=ami_id, user=user, instance_type=instance_type)

    environment.wait_for_instances("running")

    def check_date():
        return run("date", quiet=True)

    # @parallel
    def get_provides_list():
        sudo("yum -q -y install yum-utils", quiet=False)
        return sudo('repoquery --provides -a | cut -f 1 -d " " | sort -u', quiet=True)

    env.user = default_user
    env.password = "There Is No Password in EC2 But Fabric Wants to Have One :-("
    env.no_keys = True
    env.key = environment.keypair.material
    env.disable_known_hosts = True
    env.connection_attempts = 50
    env.timeout = 10

    instance_for_host = dict((instance.ip_address, instance) for instance in environment.instances)
    host_list = [instance.user + "@" + instance.ip_address for instance in environment.instances]
    result_list = execute(get_provides_list, hosts=host_list)
    for host, provides_list in result_list.items():
        print(host)
        instance = instance_for_host[host]
        print("Host {ip_address} is {image_id} return code is {0.return_code}".format(provides_list, **vars(instance)))
        if provides_list:
            file_name = "{image_id}_{image_name}_{image_description}.txt".format(**vars(instance))
            with open(file_name, "w") as output_file:
                output_file.write(provides_list)
                logger.info(
                    "Wrote result for {0} from {1} to {2}".format(instance.image_id, instance.id, output_file.name))
        else:
            logger.error("Could not gather RPM provides list from {0}".format(instance.id))


if __name__ == '__main__':
    logging.basicConfig(format='%(levelname)s: %(message)s')

    arguments = docopt(__doc__, version='0')

    if arguments["--debug"]:
        logger.setLevel(logging.DEBUG)
    elif arguments["--verbose"]:
        logger.setLevel(logging.INFO)

    try:
        run_main(aws_region=arguments["--region"],
                 instance_type=arguments["--type"],
                 vpc_id=arguments["VPC_ID"],
                 user_at_ami_id_list=arguments["USER@AMI_ID"],
                 default_user=arguments["--defaultuser"])
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.exception(e)


