#!/usr/local/bin/python3

import os, sys, pprint, logging, time, datetime
import Inventory_Modules
import argparse, boto3
from colorama import init,Fore,Back,Style
from botocore.exceptions import ClientError, NoCredentialsError

'''
TODO:
	- Enable this script to accept a Session Token to allow for Federated users
	- Pythonize the whole thing
	- More Commenting throughout script
	- There are four possible use-cases:
		- The stack exists as an association within the stackset AND it exists within the child account (typical)
			- We should remove the stackset-association with "--RetainStacks=False" and that will remove the child stack in the child account.
		- The stack exists as an association within the stackset, but has been manually deleted within the child account
			- If we remove the stackset-association with "--RetainStacks=False", it won't error, even when the stack doesn't exist within the child.
			- There is a special use case here where the child account has been deleted or suspended. This is a difficult use-case to test.
		- The stack doesn't exist within the stackset association, but DOES exist within the child account (because its association was removed from the stackset)
			- The only way to remove this is to remove the stack from the child account. This would have to be done after having found the stack within the child account. This will be a ToDo for later...
		- The stack doesn't exist within the child account, nor within the stack-set
			- Nothing to do here
'''

###################


def randomString(stringLength=10):
	import random, string
	# Generate a random string of fixed length
	letters = string.ascii_lowercase
	return ''.join(random.choice(letters) for i in range(stringLength))

def RemoveTermProtection(fProfile,fAllInstances):
	for i in range(len(fAllInstances)):
		logging.warning("Profile: %s | Region: %s | ChildAccount: %s" % (fProfile,fAllInstances[i]['ChildRegion'],fAllInstances[i]['ChildAccount']))
		session_cfn=Inventory_Modules.get_child_access(fProfile,fAllInstances[i]['ChildRegion'],fAllInstances[i]['ChildAccount'])
		client_cfn=session_cfn.client('cloudformation')
		try:
			response=client_cfn.update_termination_protection(
				EnableTerminationProtection=False,
				StackName=fAllInstances[i]['StackName']
			)
		except Exception as e:
			if e.response['Error']['Code'] == 'ValidationError':
				logging.info("Caught exception 'ValidationError', ignoring the exception...")
				print()
				pass

		logging.info("Stack %s had termination protection removed from it in Account %s in Region %s" % (fAllInstances[i]['StackName'],fAllInstances[i]['ChildAccount'],fAllInstances[i]['ChildRegion']))
	return (True)

###################

init()

parser = argparse.ArgumentParser(
	description="We\'re going to find all resources within any of the profiles we have access to.",
	prefix_chars='-+/')
parser.add_argument(
	"-p","--profile",
	dest="pProfile",
	metavar="profile to use",
	help="You need to specify a specific ROOT profile")
parser.add_argument(
	"-f","--fragment",
	dest="pStackfrag",
	nargs="*",
	metavar="CloudFormation stack fragment",
	default=["all"],
	help="List containing fragment(s) of the cloudformation stack or stackset(s) you want to check for.")
parser.add_argument(
	"-k","--skip",
	dest="pSkipAccounts",
	nargs="*",
	metavar="Accounts to leave alone",
	default=[],
	help="These are the account numbers you don't want to screw with. Likely the core accounts.")
parser.add_argument(
	"-r","--region",
	dest="pRegion",
	metavar="region name string",
	default="us-east-1",
	help="The Master region you want to check for StackSets. Only one region is checked per script run.")
parser.add_argument(
	"-R","--Remove",
	dest="pRemove",
	metavar="Account to remove from stacksets",
	help="The Account number you want removed from ALL of the stacksets and ALL of the regions it's been found.")
parser.add_argument(
	'+delete',
	help="[Default] Do a Dry-run; if this parameter is specified, we'll delete stacksets we find, with no additional confirmation.",
	action="store_const",
	const=False,
	default=True,
	dest="DryRun")
parser.add_argument(
	'-v',
	help="Be verbose",
	action="store_const",
	dest="loglevel",
	const=logging.ERROR, # args.loglevel = 40
	default=logging.CRITICAL) # args.loglevel = 50
parser.add_argument(
	'-vv', '--verbose',
	help="Be MORE verbose",
	action="store_const",
	dest="loglevel",
	const=logging.WARNING, # args.loglevel = 30
	default=logging.CRITICAL) # args.loglevel = 50
parser.add_argument(
	'-d',
	help="Print debugging statements",
	action="store_const",
	dest="loglevel",
	const=logging.INFO, # args.loglevel = 20
	default=logging.CRITICAL) # args.loglevel = 50
parser.add_argument(
	'-dd', '--debug',
	help="Print LOTS of debugging statements",
	action="store_const",
	dest="loglevel",
	const=logging.DEBUG,	# args.loglevel = 10
	default=logging.CRITICAL) # args.loglevel = 50
args = parser.parse_args()

pProfile=args.pProfile
pRegion=args.pRegion
pStackfrag=args.pStackfrag
AccountsToSkip=args.pSkipAccounts
verbose=args.loglevel
pdryrun=args.DryRun
pRemove=args.pRemove
logging.basicConfig(level=args.loglevel, format="[%(filename)s:%(lineno)s:%(levelname)s - %(funcName)20s() ] %(message)s")

##########################
ERASE_LINE = '\x1b[2K'

AllInstances=[]
# StackSetNames2=[]

print()

if pdryrun:
	print("You asked me to find (but not delete) stacksets that match the following:")
else:
	print("You asked me to find (and delete) stacksets that match the following:")
print("		In the ROOT profile {} and all children".format(pProfile))
print("		In these regions: {}".format(pRegion))
print("		For stacksets that contain these fragments: {}".format(pStackfrag))
print("		Specifically to find this account number: {}".format(pRemove))
print()

# Get the StackSet names from the Master Profile
StackSetNames=Inventory_Modules.find_stacksets(pProfile,pRegion,pStackfrag)
ProfileAccountNumber=Inventory_Modules.find_account_number(pProfile)
logging.info("Found %s StackSetNames that matched your fragment" % (len(StackSetNames)))
# for i in range(len(StackSetNames)):
# 	if 'AWSControlTower' in StackSetNames[i]['StackSetName']:
# 		continue
# 	else:
# 		StackSetNames2.append(StackSetNames[i])
# StackSetNames=StackSetNames2
for i in range(len(StackSetNames)):
	print(ERASE_LINE,"Looking for stacksets with '{}' string in account {} in region {}".format(StackSetNames[i]['StackSetName'],ProfileAccountNumber,pRegion),end='\r')
	StackInstances=Inventory_Modules.find_stack_instances(pProfile,pRegion,StackSetNames[i]['StackSetName'])
	logging.warning("Found %s Stack Instances within the StackSet %s" % (len(StackInstances),StackSetNames[i]['StackSetName']))
	# pprint.pprint(StackInstances)
	for j in range(len(StackInstances)):
		if not 'StackId' in StackInstances[j].keys():
			break
		if not (StackInstances[j]['Account'] == pRemove):
			logging.info("Found a stackset, but it didn't match the proper account... exiting")
			break
		# pprint.pprint(StackInstances[j])
		logging.debug("This is j: %s", str(j))
		logging.debug("This is StackId: %s", str(StackInstances[j]['StackId']))
		logging.debug("This is ChildAccount: %s", StackInstances[j]['Account'])
		logging.debug("This is ChildRegion: %s", StackInstances[j]['Region'])
		AllInstances.append({
			'ParentAccountNumber':ProfileAccountNumber,
			'ChildAccount':StackInstances[j]['Account'],
			'ChildRegion':StackInstances[j]['Region'],
			# This next line finds the value of the Child StackName (which includes a random GUID) and assigns it within our dict
			'StackName':StackInstances[j]['StackId'][StackInstances[j]['StackId'].find('/')+1:StackInstances[j]['StackId'].find('/',StackInstances[j]['StackId'].find('/')+1)],
			'StackStatus':StackInstances[j]['Status'],
			'StackSetName':StackInstances[j]['StackSetId'][:StackInstances[j]['StackSetId'].find(':')]
		})
		# pprint.pprint(AllInstances)
		# sys.exit(99)

print()
logging.error("Found %s stack instances." % (len(AllInstances)))
# pprint.pprint(AllInstances)

for i in range(len(AllInstances)):
	logging.error("Account %s in Region %s has Stack %s in status %s", AllInstances[i]['ChildAccount'], AllInstances[i]['ChildRegion'], AllInstances[i]['StackName'], AllInstances[i]['StackStatus'])

AccountList=[]
StackSetStillInUse=[]
for i in range(len(AllInstances)):
	if AllInstances[i]['ChildAccount'] in AccountsToSkip:
		StackSetStillInUse.append(AllInstances[i]['StackSetName'])
		continue
	else:
		AccountList.append(AllInstances[i]['ChildAccount'])
AccountList=list(set(AccountList))
StackSetStillInUse=list(set(StackSetStillInUse))

if pdryrun:
	print("Found {} StackSets that matched, with a total of {} instances".format(len(StackSetNames),len(AllInstances)))
	# pprint.pprint(AccountList)
	print("We're Done")
	print()
	sys.exit(0)

print("Removing {} stack instances from the {} StackSets found".format(len(AllInstances),len(StackSetNames)))

RegionList=[]
for i in range(len(AllInstances)):
	RegionList.append(AllInstances[i]['ChildRegion'])

RegionList=list(set(RegionList))

PolicyListOutput=[]
PolicyList=[]
session_org=boto3.Session(profile_name=pProfile,region_name=pRegion)
client_org=session_org.client('organizations')
PolicyListOutput=client_org.list_policies(Filter='SERVICE_CONTROL_POLICY')
for j in range(len(PolicyListOutput['Policies'])):
	if not (PolicyListOutput['Policies'][j]['Id']=='p-FullAWSAccess'):
		PolicyList.append(PolicyListOutput['Policies'][j]['Id'])
	else:
		continue

'''
This section removes the SCP policies to ensure that if there's a policy that disallows removing config or other tools, this will take care of that.
'''
NumofAccounts=len(AccountList)
for account in AccountList:
	NumofAccounts-=1
	for policy in PolicyList:
		try:
			response=client_org.detach_policy(
				PolicyId=policy,
				TargetId=account
			)
			logging.warning("Successfully detached policies from account %s" % (account))
		except Exception as e:
			if e.response['Error']['Code'] == 'OperationInProgressException':
				logging.info("Caught exception 'OperationInProgressException', handling the exception...")
				pass
			elif e.response['Error']['Code'] == 'PolicyNotAttachedException':
				logging.info("Caught exception 'PolicyNotAttachedException', handling the exception...")
				pass
			elif e.response['Error']['Code'] == 'ConcurrentModificationException':
				logging.info("Caught exception 'ConcurrentModificationException', handling the exception...")
				pass
			else:
				logging.info("Wasn't able to successfully detach policy from account %s. Maybe it's already detached?" % (account))
				break
		finally:
			logging.info("Only %s more accounts to go",str(NumofAccounts))

session_cfn=boto3.Session(profile_name=pProfile,region_name=pRegion)
for i in range(len(StackSetNames)):
	logging.warning("Removing all instances from %s StackSet" % (StackSetNames[i]['StackSetName']))
	try:
		response=Inventory_Modules.delete_stack_instances(pProfile,pRegion,AccountList,RegionList,StackSetNames[i]['StackSetName'],"Delete-"+randomString(5))
		# pprint.pprint(response)
	except Exception as e:
		if e.response['Error']['Code'] == 'StackSetNotFoundException':
			logging.info("Caught exception 'StackSetNotFoundException', ignoring the exception...")
		else:
			print("Error: ",e)
			break
	StackOperationsRunning=True
	client_cfn=session_cfn.client('cloudformation')
	timer=0
	InstancesToSkip=0
	while StackOperationsRunning:
		logging.info("Got into the While Loop")
		logging.warning(StackSetNames[i]['StackSetName'])
		try:
			response1=client_cfn.list_stack_set_operations(StackSetName=StackSetNames[i]['StackSetName'])['Summaries'][0]['Status']
			logging.info("StackSet Operation state is %s" % response1)
			response2=client_cfn.list_stack_instances(StackSetName=StackSetNames[i]['StackSetName'])['Summaries']
			logging.info("There are still %s instances left" % len(response2))
			for j in range(len(response2)):
				if response2[j]['Account'] in AccountsToSkip:
					InstancesToSkip+=1
			InstancesLeft=len(response2)-InstancesToSkip
			StackOperationsRunning=(response1 == 'RUNNING')
			logging.info("StackOperationsRunning is %s" % StackOperationsRunning)
			if StackOperationsRunning:
				print(ERASE_LINE+"Waiting {} seconds for {} to be fully deleted. There's still {} instances left.".format(timer,StackSetNames[i]['StackSetName'],len(response2)),end='\r')
				time.sleep(10)
				timer+=10
		except Exception as e:
			# if e.response['Error']['Code'] == 'StackSetNotFoundException':
			# 	logging.info("Caught exception 'StackSetNotFoundException', ignoring the exception...")
			# 	StackOperationsRunning=True
			# 	pass
			# else:
				print("Error: ",e)
				break

print("Now deleting {} stacksets from {} Profile".format(len(StackSetNames)-len(StackSetStillInUse),pProfile))

try:
	for i in range(len(StackSetNames)):
		# pprint.pprint(StackSetNames[i])
		# pprint.pprint(StackSetStillInUse)
		if StackSetNames[i]['StackSetName'] in StackSetStillInUse:
			continue
		else:
			response=Inventory_Modules.delete_stackset(pProfile,pRegion,StackSetNames[i]['StackSetName'])
			logging.warning("StackSet %s has been deleted from Root account %s in region %s" % (StackSetNames[i]['StackSetName'],pProfile,pRegion))
except Exception as e:
	pprint.pprint(e)
	pass

print()
print("Thanks for using this script...")
print()
