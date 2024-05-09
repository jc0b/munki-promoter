#!/usr/local/autopkg/python

# author: Jacob Burley <jacob.burley@mollie.com>

# adapted from a script by Arjen van Bochoven (https://github.com/bochoven)

import datetime
import plistlib
import logging
import os
import sys
import optparse
import urllib.request
import urllib.parse
import json
import ssl

logging.basicConfig(format='%(asctime)s - %(levelname)s: %(message)s',
                    datefmt='%m/%d/%Y %I:%M:%S %p',
                    level=logging.DEBUG,
                    stream=sys.stdout)

try:
    import certifi
    import yaml
except ImportError as e:
    logging.error(e)
    logging.error("Please install the necessary dependencies with 'python3 -m pip install -r requirements.txt'")


"""
Neat thing to do here would be to build a linked list to determine the order of things to do
ORRRR do it all in-memory in one go so you don't automatically bump stuff
"""
promotions=[
    {
        'name': 'testtostaging',
        'src': ['test'],
        'tgt': ['staging']
    },
    {
        'name': 'autopkgtostaging',
        'src': ['autopkg'],
        'tgt': ['staging']
    },
    {
        'name': 'stagingtoproduction',
        'src': ['staging'],
        'tgt': ['production']
    }
]

try:

    with open("configuration.yml", "r") as config_yaml:
        try:
            deferral_configuration = yaml.safe_load(config_yaml)
        except yaml.YAMLError as e:
            logging.error(e)
            sys.exit(1)
except FileNotFoundError as fnf:
        logging.warning("No configuration.yml file was found. Proceeding with defaults...")
        deferral_configuration = {}
        for promotion in promotions:
            deferral_configuration[promotion["name"]] = []

todays_date = datetime.datetime.now()

DEFAULT_DEFERRAL_DAYS = 7

_BOOLMAP = {
    'y': True,
    'yes': True,
    't': True,
    'true': True,
    'on': True,
    '1': True,
    'n': False,
    'no': False,
    'f': False,
    'false': False,
    'off': False,
    '0': False
}

MUNKI_ROOT_PATH='/Users/Shared/munki-repo'
MUNKI_PKGSINFO_DIR_NAME = 'pkgsinfo'


def strtobool(value):
    try:
        return _BOOLMAP[str(value).lower()]
    except KeyError:
        raise ValueError('"{}" is not a valid bool value'.format(value))

def user_yes_no_query(question):
    print(f'{question} [y/n] ', end='')
    while True:
        try:
            return strtobool(input().lower())
        except ValueError:
            print('Please respond with \'y\' or \'n\'.\n')

def check_up_for_promotion(promotion_name, pkginfo):
    pkginfo_creation_date = pkginfo["_metadata"]["creation_date"]
    # get datetime object for the pkginfo item creation
    # a->s = 5
    # s->p = 2

    promotion_deferral = DEFAULT_DEFERRAL_DAYS #7
    if promotion_name == 'stagingtoproduction':
        promotion_deferral += DEFAULT_DEFERRAL_DAYS # production promotions should happen after two cycles, so 14 days by default

    if pkginfo["name"] in deferral_configuration[promotion_name]:
        # we have configuration!
        promotion_deferral = deferral_configuration[promotion_name][pkginfo["name"]] #2
        if promotion_name == 'stagingtoproduction':
            # we should check to see if we have another set of configuration for autopkgtostaging so we can calculate the cutoff
            if pkginfo["name"] in deferral_configuration['autopkgtostaging']:
                promotion_deferral += deferral_configuration['autopkgtostaging'][pkginfo["name"]] # cutoff = a->s + s->p
            else:
                promotion_deferral += DEFAULT_DEFERRAL_DAYS
    return (todays_date - pkginfo_creation_date).days >= promotion_deferral

def promotion_exists(promotion_name):
    for promotion in promotions:
        if promotion['name'] == promotion_name:
            return True

def print_promotions():
    for promotion in promotions:
        print(f"{promotion['name']}:")
        print(f"   {', '.join(promotion['src'])} -> {', '.join(promotion['tgt'])}")

def get_promotion_tgt(promotion_name):
    for promotion in promotions:
        if promotion['name'] == promotion_name:
            return promotion['tgt']

def get_other_promotions(promotion_name):
    result = []
    for promotion in promotions:
        if promotion['name'] != promotion_name:
            result.append(promotion['name'])
    return result

def get_promotion(pkginfo, promotion_name):
    for promotion in promotions:
        if promotion['name'] == promotion_name and promotion['src'] == pkginfo['catalogs']:
            pkginfo['catalogs'] = promotion['tgt']
            return True

def get_promotion_metadata(pkginfo):
    return [pkginfo['name'], pkginfo['version']]

def verify_pkgsinfo_folder(path):
   # Check that the path for the pkgsinfo exists
   if not os.path.isdir(path):
      logging.error("Your pkgsinfo path is not valid. Please check your MUNKI_ROOT_PATH and MUNKI_PKGSINFO_DIR_NAME values.")
      sys.exit(1)
   if not os.access(path, os.W_OK):
      logging.error(f"You don't have access to {path}")
      sys.exit(1)

def process_pkgsinfo_files(pkgsinfo_path, promotion_name, write = False):
    found_promotions = []
    for root, dirs, files in os.walk(pkgsinfo_path):
        for file in files:
            # Skip files that start with a period
            if file.startswith("."):
                continue
            fullfile = os.path.join(root, file)
            fp = open(fullfile, "rb+")
            pkginfo = plistlib.load(fp, fmt=None)
            if get_promotion(pkginfo, promotion_name):
                promotion_metadata = get_promotion_metadata(pkginfo)
                promotion_metadata.insert(0, file)
                if check_up_for_promotion(promotion_name, pkginfo):
                    found_promotions.append(promotion_metadata)
                    if write:
                        logging.info(f"Promoting {fullfile} to {pkginfo['catalogs']}")
                        fp.seek(0)
                        plistlib.dump(pkginfo, fp, fmt=plistlib.FMT_XML)
                        fp.truncate()
    return found_promotions

def print_header(name):
    print(f"***\n* Promoting the catalogs of the following pkgsinfo files to {get_promotion_tgt(name)}\n***")

def print_found_promotions(promotion_list):
    for promotion in promotion_list:
        print(f"{promotion[1]} - {promotion[2]}")

def print_promotion_count(promotion_list):
    print(f'{len(promotion_list)} pkginfo files promoted')

def print_promotion_not_found(name):
    print(f'Promotion "{name}" not found, use --list to see valid names.')

def send_webhook(promotion_name, run_promotions, url):
    data = json.dumps(build_slack_blocks(promotion_name, run_promotions)).encode('utf-8') #data should be in bytes
    headers = {'Content-Type': 'application/json'}
    req = urllib.request.Request(url, data, headers)
    resp = urllib.request.urlopen(req, context=ssl.create_default_context(cafile=certifi.where()))
    response = resp.read()
    if(resp.status == 200):
        logging.info("Webhook sent successfully!")
    else:
        logging.error(f"HTTP response {resp.status} when sending the webhook.")

def build_slack_blocks(promotion_name, run_promotions):
    run_promotions = sorted(run_promotions, key = lambda x: x[1])
    promotion_text = ""
    for item in run_promotions:
        promotion_text += f"{item[1]} - {item[2]}\n"
    payload = {}
    payload['blocks'] = []
    payload['blocks'].append({"type": "header", "text": {"type": "plain_text"}})
    payload['blocks'][0]['text']['text'] = f"New items automatically promoted to Munki {promotion_name} catalog!"
    payload['blocks'].append({"type": "divider"})
    payload['blocks'].append({"type": "section", "text": {"type": "mrkdwn", "text": promotion_text.strip()}})
    payload['blocks'].append({"type": "context", "elements": [{"type": "mrkdwn", "text": ":monkey_face: This message brought to you by <https://gitlab.molops.io/cit/cpe/munki-promoter|munki-promoter>."}]})

    return payload

def main():
    """Main"""

    parser = optparse.OptionParser()
    parser.set_usage('Usage: %prog [options]')

    parser.add_option(
        '--name', '-n', default='',
        help='Name of promotion to run, use --list to see possible values.')
    parser.add_option(
        '--list', '-l', action='store_true',
        help='Get list of possible promotions.')
    parser.add_option(
        '--path', default=MUNKI_ROOT_PATH,
        help=f'Optional path to the munki root directory,\ndefaults to {MUNKI_ROOT_PATH}')
    parser.add_option(
        '--auto', '-a', action='store_true',
        help='Run without interaction.')

    options, args = parser.parse_args()
    
    pkgsinfo_path = os.path.join(options.path, MUNKI_PKGSINFO_DIR_NAME)
    verify_pkgsinfo_folder(pkgsinfo_path)

    try:
        slack_webhook_url = os.environ['SLACK_WEBHOOK']
    except KeyError as e:
        logging.warning(f"The {e} environment variable is undefined. Webhooks will not be sent.")
        slack_webhook_url = None

    if options.list:
        print_promotions()
        sys.exit(0)
    
    if options.name and options.auto:
        if not promotion_exists(options.name):
            print_promotion_not_found(options.name)
            sys.exit(1)
        run_promotions = process_pkgsinfo_files(pkgsinfo_path, options.name, True)
        print_promotion_count(run_promotions)
        if slack_webhook_url is not None and len(run_promotions) > 0:
            send_webhook(get_promotion_tgt(options.name)[-1], run_promotions, slack_webhook_url)
        sys.exit(0)
        
    if options.name:
        if not promotion_exists(options.name):
            print_promotion_not_found(options.name)
            sys.exit(1)
        found_promotions = process_pkgsinfo_files(pkgsinfo_path, options.name)
        if len(found_promotions):
            print_header(options.name)
            print_found_promotions(found_promotions)
            if user_yes_no_query('Do you want to promote these?'):
                process_pkgsinfo_files(pkgsinfo_path, options.name, True)
                print_promotion_count(found_promotions)
            else:
                print('Ok, aborted..')
                sys.exit(1)
        else:
            print('No promotions found')
    else:
        parser.print_help()
if __name__ == '__main__':
    main()