aws-distro-rpm-comparison
=========================

Compare available RPMs in different Linux distros on AWS.

Example usage (for eu-west-1):
```
./aws-distro-rpm-comparison.py --debug vpc-123456 root@ami-30ff5c47 ec2-user@ami-6e7bd919 ec2-user@ami-8cff51fb
```

Notes
-----

1. This will grab the first subnet returned by the boto [`get_all_subnets`](http://boto.readthedocs.org/en/latest/ref/vpc.html?highlight=vpc#boto.vpc.VPCConnection.get_all_subnets) function.
2. The instances require public IP addresses for this to work.
3. Because of note 1 and 2, you should have a VPC with a single subnet with an internet gateway attached, and the subnet needs to auto-assign a public IP to its instances.