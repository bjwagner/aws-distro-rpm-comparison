#!/usr/bin/python
"""Create EC2 instances with different Linux distros and compare
the available RPMs on them.

Usage:
  aws-distro-rpm-comparions.py [options] VPC_ID AMI_ID...

Arguments:
  VPC_ID  VPC_ID to use
  AMI_ID  AMI IDs to use

Options:
  -h --help            show this help message and exit
  --version            show version and exit
  --region=REGION      use this region [default: eu-west-1]
  --type=TYPE          EC2 instance type [default: t2.micro]
"""
from __future__ import print_function

from docopt import docopt
import boto, boto.ec2, boto.vpc
import os, platform, sys, time
import atexit
from pprint import pprint


def info(*objs):
    print("INFO: ", *objs, file=sys.stderr)


class Environment(object):
    wait_delay_in_seconds = 10

    def decommission(self):
        info("Removing Environment")

        try:
            if self.instances:
                instance_ids = [i.id for i in self.instances]
                info("Terminating Instances {0}".format(", ".join(instance_ids)))
                self.conn.terminate_instances(instance_ids)
                running_instances = list(self.instances)
                while running_instances:
                    info("The following instances are still running: {0}".format(", ".join([i.id+" "+i.state for i in running_instances])))
                    time.sleep(self.wait_delay_in_seconds)
                    for i in running_instances:
                        i.update()
                    running_instances = [i for i in running_instances if i.state != "terminated"]
        except Exception as e:
            print(e)

        try:
            if self.securitygroup.delete():
                info("Deleted Security Group")
        except AttributeError:
            pass

        try:
            if self.keypair.delete():
                info("Deleted Key Pair")
        except AttributeError:
            pass


    def __init__(self, region, vpc_id):
        atexit.register(self.decommission)
        try:
            self.conn = boto.ec2.connect_to_region(region)
            self.vpc_id = vpc_id
            self.myid = os.environ["USER"] + "_" + platform.node()
            self.keypair = self.conn.create_key_pair(self.myid)
            info("Created Key Pair {0}".format(self.keypair.name))
            self.securitygroup = self.conn.create_security_group(name=self.myid, description='Temporary Security Group',
                                                                 vpc_id=self.vpc_id)
            info("Created Security Group {0}".format(self.securitygroup.id))
            self.securitygroup.authorize('tcp', 22, 22, '0.0.0.0/0')
            self.first_subnet = boto.vpc.connect_to_region(region).get_all_subnets()[0]
            self.instances = []
        except boto.exception.EC2ResponseError as e:
            raise Exception("BOTO Error: {0.reason}\n{0.body}".format(e))


    def run_instances(self, ami_id, type):
        instances = self.conn.run_instances(ami_ids[0], security_group_ids=[self.securitygroup.id],
                                            instance_type=type, subnet_id=self.first_subnet.id).instances
        self.instances.extend(instances)
        for i in instances:
            info("Created Instance {0.id}".format(i))
        time.sleep(1) # give AWS some time to collect its wits
        return instances

    def wait_for_instances(self, target_state, timeout_in_seconds=120):
        end_time = time.time() + timeout_in_seconds
        wrong_state_instances = list(self.instances)
        while time.time() <= end_time:
            for i in wrong_state_instances:
                i.update()
            wrong_state_instances = [i for i in wrong_state_instances if i.state != target_state]
            if wrong_state_instances:
                info("The following instances still have the wrong state: {0}".format(", ".join([i.id+" "+i.state for i in wrong_state_instances])))
                time.sleep(self.wait_delay_in_seconds)
            else:
                return True
        raise Exception("Could not reach {target_state} state after waiting {timeout_in_seconds} seconds".format(locals()))


def run(region, type, vpc_id, ami_ids):
    environment = Environment(region=region, vpc_id=vpc_id)
    e = environment.run_instances(ami_ids[0], type)
    environment.wait_for_instances("running")
    pprint(vars(e[0]))


if __name__ == '__main__':
    arguments = docopt(__doc__, version='0')
    ami_ids = arguments["AMI_ID"]
    run(region=arguments["--region"], type=arguments["--type"], vpc_id=arguments["VPC_ID"], ami_ids=arguments["AMI_ID"])


