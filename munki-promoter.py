#!/usr/bin/env python3

# authors: Jacob Burley (j@jc0b.computer) and Kai (https://github.com/kaiobendrauf)

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

DEFAULT_CONFIG = {
	"promotions": {
		"autopkg": {
			"promote_to": ["staging", "autopkg"] },
		"staging": {
			"promote_from": ["staging", "autopkg"],
			"promote_to": ["production"] } },
	"default_days_in_catalog" : 7 }

CONFIG_FILE = "config.yml"
MUNKI_PATH='/Users/Shared/munki-repo/pkgsinfo'

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

using_default_config = False
	
# ----------------------------------------
# 				Strings
# ----------------------------------------

def and_str(l):
	if len(l) == 1:
		return l[0]
	result = ""
	for i, s in enumerate(l):
		result += s 
		if i == len(l) - 2:
			result += " and " 
		elif i < len(l) - 2:
			result += ", "
	return result

def white_space_pad_strings(l):
	maxlen = len(max(l, key=len))
	result = [s + (' ' * (maxlen - len(s))) for s in l]
	return result 

def describe_promotion(promotion, promote_to, names, versions, custom_item_descriptions):
	result = "\n------------------------------------------------------------------------------------\n"
	result += f'                        Applying promotion "{promotion}"\n'
	result += f"   Promoting the catalogs of the following pkgsinfo files to {promote_to}\n"
	result += "------------------------------------------------------------------------------------\n"
	if len(names) > 0:
		names = white_space_pad_strings(names)
		for i, name in enumerate(names):
			result += (f"{name} - {versions[i]}\n")
	if len(custom_item_descriptions['names']) > 0:
		custom_names = white_space_pad_strings(custom_item_descriptions['names'])
		custom_versions = white_space_pad_strings(custom_item_descriptions['versions'])
		custom_promote_tos = custom_item_descriptions['promote_tos']
		result += "The following pkgsinfo files are custom items that impact which catalog they will be promoted to:\n"
		for i, name in enumerate(custom_names):
			result += f"{name} - {custom_versions[i]} - will be promoted to {and_str(custom_promote_tos[i])} \n"
	return result

# ----------------------------------------
# 			Configurations
# ----------------------------------------
def get_config(config_path, is_config_specified) -> dict:
	try:
		global yaml
		import yaml
		if not os.path.exists(config_path):
			# import success BUT no file 
			if is_config_specified:
				# file was user provided -> error: user provided file should exist
				logging.error(f"Configuration file {config_path} is not present.")
				sys.exit(1)
			else:
				# file was not user provided -> warning: use defauls
				logging.warning("No configuration file is present. Will continue with default settings.")
				return DEFAULT_CONFIG
		# import success AND file exists
		if not os.access(config_path, os.R_OK):
			logging.error(f"You don't have access to {config_path}")
			sys.exit(1)	
		with open(config_path, "r") as config_yaml:
			logging.info(f"Loading {config_path} ...")
			try:
				result = yaml.safe_load(config_yaml)
				logging.info(f"Successfully loaded {config_path}!")
				return result
			except yaml.YAMLError as e:
				logging.error(f"Unable to load {config_path}")
				sys.exit(1)
	except ModuleNotFoundError as e:
		# import unsuccessful
		if os.path.exists(config_path):
			# import unsuccessful AND file exists -> error: should be able to read file
			logging.error(f"Missing dependency to read configuration file: {e}")
			sys.exit(1)
		elif is_config_specified:
			# import unsuccessful AND no file BUT file was user provided -> error: user provided file should be readable
			logging.error(f"Missing dependency to read configuration file: {e}")
			logging.error(f"Configuration file {config_path} is not present.")
			sys.exit(1)
		else:
			# import unsuccessful But no file -> warning: use defaults
			logging.warning("PyYAML library could not be loaded, but no configuration file is present. Will continue with default settings.")
			return DEFAULT_CONFIG

def print_promotions(config, config_path):
	promotion_strings = []
	from_strings = []
	to_strings = []
	error_promotions = []
	error_descriptions = []
	promotions_found = False
	if config and "promotions" in config:
		promotions = config["promotions"]
		for promotion in promotions:
			if is_valid_promotion(promotion, promotions):
				to_str = and_str(promotions[promotion]["promote_to"])
				from_str = promotion
				if "promote_from" in promotions[promotion]:
					if promotions[promotion]["promote_from"] and type(promotions[promotion]["promote_from"]) == list and len(promotions[promotion]["promote_from"]) > 0:
						from_str = and_str(promotions[promotion]["promote_from"])
				promotion_strings.append(promotion)
				from_strings.append(from_str)
				to_strings.append(to_str)
				promotions_found = True
			else:
				# not valid promotion
				error_promotions.append(promotion)
				error_descriptions.append(f"improperly defined! Which catalog(s) promotion \"{promotion}\" promotes to is undefined. Promotions can be configured in {config_path}.")
	if promotions_found:
		promotion_strings = promotion_strings + error_promotions
		promotion_strings = white_space_pad_strings(promotion_strings)
		from_strings = white_space_pad_strings(from_strings)
		len_from = len(from_strings)
		for i, from_str in enumerate(from_strings):
			print(promotion_strings[i] + " : promotes from " +  from_str + " to " + to_strings[i])
		for i, error_string in enumerate(error_descriptions):
			print(promotion_strings[i + len_from] + " : " + error_string)
	else:
		print(f"No promotions are currently defined. Promotions can be configured in {config_path}.")

def does_promotion_exist(promotion, promotions):
	return promotions and type(promotions) == dict and promotion in promotions

def is_valid_promotion(promotion, promotions):
	if type(promotions[promotion]) == dict:
		if "promote_to" in promotions[promotion] and type(promotions[promotion]["promote_to"]) == list:
			if len(promotions[promotion]["promote_to"]) > 0:
				return True
	return False

def get_promotion_info(promotion, promotions, config, config_path):
	if is_valid_promotion(promotion, promotions):
		# promotion is valid so promote_to is defined
		promote_to = promotions[promotion]["promote_to"]
		# find our where to promote from, using default of promotion name if necessary
		promote_from = [promotion]
		if "promote_from" in promotions[promotion] and type(promotions[promotion]["promote_from"]) == list and len(promotions[promotion]["promote_to"]) > 0:
			promote_from = promotions[promotion]["promote_from"]
		# get custom items
		custom_items = dict()
		if "custom_items" in promotions[promotion] and type(promotions[promotion]["custom_items"]) == dict:
			custom_items = promotions[promotion]["custom_items"]
		# get days
		if "days_in_catalog" in promotions[promotion]:
			days = promotions[promotion]["days_in_catalog"]
		elif "default_days_in_catalog" in config:
			days = config["default_days_in_catalog"]
		else:
			logging.error(f'Promotion "{promotion}" improperly defined! `days_in_catalog` is undefined and no `default_days_in_catalog` has been defined. Promotions can be configured in {config_path}. Use --list to see valid catalogs to promote.')
			sys.exit(1)
		return promote_to, promote_from, days, custom_items
	else:
		# error: catalog has no promotions
		logging.error(f'Promotion "{promotion}" improperly defined! Which catalog(s) promotion "{promotion}" promotes to is undefined. Promotions can be configured in {config_path}. Use --list to see valid catalogs to promote.')
		sys.exit(1)

def check_selection_specified_correctly(config, config_path):
	if config and "selection" in config:
		if "type" in config["selection"]:
			if config["selection"]["type"] == "inclusion":
				if "items" not in config["selection"] or type(config["selection"]["items"]) != list or len(config["selection"]["items"]) < 1:
					logging.warning(f"Selection type set to inclusion but no list of items defined in {config_path}. No items will be considered.")
			elif config["selection"]["type"] == "exclusion":
				if "items" not in config["selection"] or type(config["selection"]["items"]) != list or len(config["selection"]["items"]) < 1:
					logging.warning(f"Selection type set to exclusion but no list of items defined in {config_path}. All items will be considered.")
			elif config["selection"]["type"] != "all":
				logging.error(f'Selection type set incorrectly in {config_path}. Selection type must be "inclusion", "exclusion", or "all", but was set to {config["selection"]["type"]}.')
				sys.exit(1)
		else:
			logging.warning(f"Selection key found in {config_path}, but no selection type found. All items will be considered.")

# ----------------------------------------
# 					Slack
# ----------------------------------------
def send_slack_webhook(slack_url, slack_blocks):
	context_block = {"type": "context", "elements": [{"type": "mrkdwn", "text": ":monkey_face: This message brought to you by <https://github.com/jc0b/munki-promoter|munki-promoter>."}]}
	slack_blocks.append(context_block)
	slack_blocks.append({"type": "divider"})
	slack_dict = {"blocks" : slack_blocks}
	data = json.dumps(slack_dict).encode('utf-8') #data should be in bytes
	headers = {'Content-Type': 'application/json'}
	req = urllib.request.Request(slack_url, data, headers)
	resp = urllib.request.urlopen(req, context=ssl.create_default_context(cafile=certifi.where()))
	response = resp.read()
	if(resp.status == 200):
		logging.info("Slack webhook sent successfully!")
	else:
		logging.error(f"Slack webhook could not be sent. HTTP response {resp.status}.")
		sys.exit(1)

def add_to_slack_blocks(blocks, promotion, promote_to, names, versions, custom_item_descriptions):
	heading_element = {"type": "text", "text": f'Applied promotion "{promotion}".', "style": {"bold": True}}
	blocks.append({"type": "rich_text", "elements": [{"type": "rich_text_section","elements": [heading_element]}]})

	if len(names) > 0:
		if len(promote_to) > 1:
			subheading = {"type": "text", "text": f"The following items have been promoted to Munki {and_str(promote_to)} catalogs:"}
		else:
			subheading = {"type": "text", "text": f"The following items have been promoted to Munki {promote_to[0]} catalog:"}
		blocks.append({"type": "rich_text", "elements": [{"type": "rich_text_section","elements": [subheading]}]})
		item_blocks = []
		for i, name in enumerate(names):
			item_blocks.append({"type": "rich_text_section", "elements": [{"type": "text", "text": f"{name} - {versions[i]}\n"}]})
		blocks.append({"type": "rich_text", "elements": [{"type": "rich_text_list", "style": "bullet", "indent": 0, "border": 0, "elements": item_blocks}]})

	custom_names = custom_item_descriptions['names']
	custom_versions = custom_item_descriptions['versions']
	custom_promote_tos = custom_item_descriptions['promote_tos']
	if len(custom_names) > 0:
		custom_subheading = {"type": "text", "text": f"The following custom items have been promoted:"}
		blocks.append({"type": "rich_text", "elements": [{"type": "rich_text_section","elements": [custom_subheading]}]})
		custom_item_blocks = []
		for i, name in enumerate(custom_names):
			if len(custom_promote_tos[i]) > 1:
				custom_item_blocks.append({"type": "rich_text_section", "elements": [{"type": "text", "text": f"{name} - {custom_versions[i]} - promoted to Munki {and_str(custom_promote_tos[i])} catalogs\n"}]})
			else:
				custom_item_blocks.append({"type": "rich_text_section", "elements": [{"type": "text", "text": f"{name} - {custom_versions[i]} - promoted to Munki {and_str(custom_promote_tos[i])} catalog\n"}]})
		blocks.append({"type": "rich_text", "elements": [{"type": "rich_text_list", "style": "bullet", "indent": 0, "border": 0, "elements": custom_item_blocks}]})

	return blocks

def add_slack_div(blocks):
	blocks.append({"type": "divider"})
	return blocks

def setup_slack_blocks():
	try:
		global certifi
		import certifi
	except ImportError as e:
			logging.error(f"Certifi library could not be loaded.")
			logging.error("You can install the necessary dependencies with 'python3 -m pip install -r requirements.txt'")
			sys.exit(1)
	header_block = {"type": "header", "text": {"type": "plain_text", "text": "New items automatically promoted in Munki", "emoji": True}}
	return [header_block]

# ----------------------------------------
#			Markdown change log
# ----------------------------------------
def write_md_file(md_file, md):
	try:
		f = open(md_file, "w")
		f.write(md)
		f.close()
		logging.info("Markdown file successfully updated.")
	except Exception as e:
		logging.error(f"Unable to write to {md_file}")
		sys.exit(1)


def md_description(promotion, promote_to, names, versions, custom_item_descriptions):
	result = f'Applied promotion "{promotion}".\n'
	if len(names) > 0:
		if len(promote_to) > 1:
			result += f"The following items have been automatically promoted to Munki {and_str(promote_to)} catalogs:\n"
		else:
			result += f"The following items have been automatically promoted to Munki {promote_to[0]} catalog:\n"
		for i, name in enumerate(names):
			result += f"- {name}: {versions[i]}\n"

	custom_names = custom_item_descriptions['names']
	custom_versions = custom_item_descriptions['versions']
	custom_promote_tos = custom_item_descriptions['promote_tos']
	if len(custom_names) > 0:
		result += "The following custom items have been automatically promoted:\n"
		for i, name in enumerate(custom_names):
			if len(custom_promote_tos[i]) > 1:
				result += f"- {name}: {custom_versions[i]} (promoted to Munki {and_str(custom_promote_tos[i])} catalogs)\n"
			else:
				result += f"- {name}: {custom_versions[i]} (promoted to Munki {and_str(custom_promote_tos[i])} catalog)\n"
	result += "\n"
	return result

# ----------------------------------------
#					Munki
# ----------------------------------------
def get_munki_paths(munki_path):
	result = []
	if not os.path.exists(munki_path):
			logging.error(f"Path to munki root directory {munki_path} does not exist.")
			sys.exit(1)
	if not os.access(munki_path, os.W_OK):
		logging.error(f"You don't have access to {munki_path}")
		sys.exit(1)
	for root, dirs, files in os.walk(munki_path):
		# collect all full paths where file does not start with a period (hidden files)
		result += [os.path.join(root, file) for file in files if not file.startswith(".")] # check file does not start with a period (hidden files)
	return result

def prep_all_promotions(config, munki_path, config_path):
	names = dict()
	versions = dict()
	custom_item_descriptions = dict()
	prepped_promotions = []
	promote_tos = dict()
	if config and "promotions" in config and type(config["promotions"]) == dict:
		promotions = config["promotions"]
		for file in get_munki_paths(munki_path):
			try:
				# open file
				with open(file, "rb+") as fp:
					try:
						# load file
						pkginfo = plistlib.load(fp, fmt=None)
						# prep individual pkginfo for promotion
						for promotion in config["promotions"]:
							promote_to, promote_from, days, custom_items = get_promotion_info(promotion, promotions, config, config_path)
							item_name, item_version, item_promotion, custom_promote_to = prep_item_for_promotion(pkginfo, promote_to, promote_from, days, custom_items, file)
							if item_name and check_selection(config, item_name): # would be None if not eligible for promotion
								if not (promotion in names):
									# first of this promotion type
									names[promotion] = []
									versions[promotion] = []
									custom_item_descriptions[promotion] = {"names": [], "versions": [], "promote_tos": []}
									promote_tos[promotion] = promote_to
								if custom_promote_to:
									custom_item_descriptions[promotion]["names"].append(item_name)
									custom_item_descriptions[promotion]["versions"].append(item_version)
									custom_item_descriptions[promotion]["promote_tos"].append(custom_promote_to)
								else:
									names[promotion].append(item_name)
									versions[promotion].append(item_version)
								prepped_promotions.append(item_promotion)
								break
					except plistlib.InvalidFileException as e:
						logging.error(f"Could not load file {file} in munki directory.")
						logging.error(e, exc_info=True)
						sys.exit(1)
			except OSError as e:
				logging.error(f"Could not open file {file} in munki directory.")
				logging.error(e, exc_info=True)
				sys.exit(1)
		return names, versions, custom_item_descriptions, prepped_promotions, promote_tos
	else:
		# error: bad yaml config
		logging.error(f'No promotions are currently defined in {config_path}.')
		sys.exit(1)

def prep_single_promotion(promotion, config, munki_path, config_path):
	if config and "promotions" in config and type(config["promotions"]) == dict:
		promotions = config["promotions"]
		if does_promotion_exist(promotion, promotions):
			promote_to, promote_from, days, custom_items = get_promotion_info(promotion, promotions, config, config_path)
			names, version, custom_item_descriptions, promotions = prep_pkgsinfo_single_promotion(promote_to, promote_from, days, custom_items, munki_path) 
			return names, version, custom_item_descriptions, promotions, promote_to
		else:
			# error: catalog does not exist
			logging.error(f'Promotion "{promotion}" not found! Use --list to see valid catalogs to promote. Promotions can be configured in {config_path}.')
			sys.exit(1)
	else:
		# error: bad yaml config
		logging.error(f'No promotions are currently defined in {config_path}.')
		sys.exit(1)

def prep_pkgsinfo_single_promotion(promote_to, promote_from, days, custom_items, munki_path):
	names = []
	versions = []
	promotions = []
	custom_item_descriptions = {"names": [], "versions": [], "promote_tos": []}
	for file in get_munki_paths(munki_path):
		try:
			# open file
			with open(file, "rb+") as fp:
				try:
					# load file
					pkginfo = plistlib.load(fp, fmt=None)
					# prep individual pkginfo for promotion
					item_name, item_version, item_promotion, custom_promote_to = prep_item_for_promotion(pkginfo, promote_to, promote_from, days, custom_items, file)
					if item_name and check_selection(config, item_name): # would be None if not eligible for promotion
						if custom_promote_to:
							custom_item_descriptions["names"].append(item_name)
							custom_item_descriptions["versions"].append(item_version)
							custom_item_descriptions["promote_tos"].append(custom_promote_to)
						else:
							names.append(item_name)
							versions.append(item_version)
						promotions.append(item_promotion)
				except plistlib.InvalidFileException as e:
					logging.error(f"Could not load file {file} in munki directory.")
					logging.error(e, exc_info=True)
					sys.exit(1)
		except OSError as e:
			logging.error(f"Could not open file {file} in munki directory.")
			logging.error(e, exc_info=True)
			sys.exit(1)
	return names, versions, custom_item_descriptions, promotions

def prep_item_for_promotion(item, promote_to, promote_from, days, custom_items, item_path):
	changed_promote_to = False
	try:

		item_architecture = item.get("supported_architectures", [])

		if item_architecture:
			item_architecture = f" ({', '.join(item_architecture)})"
		else:
			item_architecture = ""

		item_name = item["name"] + item_architecture
		item_version = item["version"]
		item_catalogs = item["catalogs"]
	except Exception as e:
		logging.error(f"File {item_path} is missing expected keys.", exc_info=True)
		sys.exit(1)
	# check if custom item
	if item_name in custom_items and type(custom_items[item_name]) == dict:
		if "days_in_catalog" in custom_items[item_name]:
			days = custom_items[item_name]["days_in_catalog"]
		if "promote_to" in custom_items[item_name] and type(custom_items[item_name]["promote_to"]) == list and len(custom_items[item_name]["promote_to"]) > 0:
			promote_to = custom_items[item_name]["promote_to"]
			changed_promote_to = True
		if "promote_from" in custom_items[item_name] and type(custom_items[item_name]["promote_from"]) == list and len(custom_items[item_name]["promote_from"]) > 0:
			promote_from = custom_items[item_name]["promote_from"]
	# check if eligable for promotion based on current catalogs
	if set(item_catalogs) == set(promote_from): # convert to set so order doesn't matter
		# check if eligable for promotion based on days
		today = datetime.datetime.now()
		last_edited_date = today
		if "_metadata" in item:
			if "munki-promoter_edit_date" in item["_metadata"]:
				last_edited_date = item["_metadata"]["munki-promoter_edit_date"]
			elif "creation_date" in item["_metadata"]:
				last_edited_date = item["_metadata"]["creation_date"]
				logging.info(f"File {item_path} is missing a last edit date so the creation date {last_edited_date} will be used with the assumption that this item has been in the current catalog(s) since creation.")
			else:
				item["_metadata"]["munki-promoter_edit_date"] = today
				logging.info(f"File {item_path} is missing a creation date so munki-promoter will set the last edit date to today.")
				try_add_metadata(item_path, item)
		else:
			item["_metadata"] = {"munki-promoter_edit_date": today}
			logging.info(f"File {item_path} is missing a creation date so munki-promoter will set the last edit date to today.")
			try_add_metadata(item_path, item)
		if last_edited_date + datetime.timedelta(days=days) < today:
			# up for promotion!
			item["catalogs"] = promote_to
			item["_metadata"]["munki-promoter_edit_date"] = today
			if changed_promote_to:
				return item_name, item_version, (item_path, item), promote_to
			else:
				return item_name, item_version, (item_path, item), None
	return None, None, None, None

def promote_items(preped_promotions):
	for item_path, item in preped_promotions:
		try:
			# open file
			with open(item_path, "rb+") as fp:
				try:
					logging.info(f"Promoting {item_path} to {item['catalogs']}")
					# make sure we are at start of file
					fp.seek(0)
					# write to file
					plistlib.dump(item, fp, fmt=plistlib.FMT_XML)
					# remove any excess of old file
					fp.truncate()
				except Exception as e:
					logging.error(f"Could not write to file {item_path} in munki directory.")
					logging.error(e, exc_info=True)
					sys.exit(1)
		except OSError as e:
			logging.error(f"Could not open file {item_path} in munki directory.")
			logging.error(e, exc_info=True)
			sys.exit(1)

def try_add_metadata(item_path, item):
	try:
		# open file
		with open(item_path, "rb+") as fp:
			try:
				logging.info(f"Adding missing metadata to file {item_path}")
				# make sure we are at start of file
				fp.seek(0)
				# write to file
				plistlib.dump(item, fp, fmt=plistlib.FMT_XML)
				# remove any excess of old file
				fp.truncate()
			except Exception as e:
				logging.warning(f"File {item_path} is missing metadata and this file can not be written to.", exc_info=True)
	except OSError as e:
			logging.warning(f"File {item_path} is missing metadata and this file can not be written to.", exc_info=True)

def prep_set_edit_date(munki_path, config, overwrite=False, promotion=None, promote_from_days=None, config_path=None):
	if promotion:
		if config and "promotions" in config and type(config["promotions"]) == dict:
			promotions = config["promotions"]
			if does_promotion_exist(promotion, promotions):
				_, promote_from, _, custom_items = get_promotion_info(promotion, promotions, config, config_path)
				return prep_pkgsinfo_edit_date(munki_path, config, promote_from=promote_from, promote_from_days=promote_from_days, custom_items=custom_items) 
			else:
				# error: catalog does not exist
				logging.error(f'Promotion "{promotion}" not found! Use --list to see valid catalogs to promote. Promotions can be configured in {config_path}.')
				sys.exit(1)
		else:
			# error: bad yaml config
			logging.error(f'No promotions are currently defined in {config_path}.')
			sys.exit(1)
	else:
		return prep_pkgsinfo_edit_date(munki_path, overwrite=overwrite) 

def prep_pkgsinfo_edit_date(munki_path, config, overwrite=False, promote_from=None, promote_from_days=None, custom_items=None):
	names = []
	changes = []
	for file in get_munki_paths(munki_path):
		try:
			# open file
			with open(file, "rb+") as fp:
				try:
					# load file
					pkginfo = plistlib.load(fp, fmt=None)
					# prep individual pkginfo for promotion
					item_name, item = prep_item_edit_date(pkginfo, file, overwrite, promote_from, promote_from_days, custom_items)
					if item_name and check_selection(config, item_name): # would be None if not eligible for promotion
						names.append(item_name)
						changes.append(item)
				except plistlib.InvalidFileException as e:
					logging.error(f"Could not load file {file} in munki directory.")
					logging.error(e, exc_info=True)
					sys.exit(1)
		except OSError as e:
			logging.error(f"Could not open file {file} in munki directory.")
			logging.error(e, exc_info=True)
			sys.exit(1)
	return names, changes

def prep_item_edit_date(item, item_path, overwrite, promote_from, promote_from_days, custom_items):
	try:
		item_name = item["name"]
		if promote_from:
			item_catalogs = item["catalogs"]
	except Exception as e:
		logging.error(f"File {item_path} is missing expected keys.", exc_info=True)
		sys.exit(1)
	# if for a specific promotion, check if custom item
	if promote_from and (item_name in custom_items and type(custom_items[item_name]) == dict):
		if "promote_from" in custom_items[item_name] and type(custom_items[item_name]["promote_from"]) == list and len(custom_items[item_name]["promote_from"]) > 0:
			promote_from = custom_items[item_name]["promote_from"]
	# check if overwriting or if value missing
	if not "_metadata" in item:
		item["_metadata"] = dict()
	if overwrite or (not "munki-promoter_edit_date" in item["_metadata"]):
		today = datetime.datetime.now()
		if promote_from:
			if set(item_catalogs) == set(promote_from):
				if not "creation_date" in item["_metadata"]:
					logging.info(f"File {item_path} is missing a creation date so munki-promoter will set the last edit date to today.")
					item["_metadata"]["munki-promoter_edit_date"] = today
					return item_name, (item_path, item)
				else:
					creation_date = item["_metadata"]["creation_date"]
					last_edited_date = creation_date + datetime.timedelta(days=promote_from_days)
					item["_metadata"]["munki-promoter_edit_date"] = last_edited_date
					return item_name, (item_path, item)
		else:
			item["_metadata"]["munki-promoter_edit_date"] = today
			return item_name, (item_path, item)
	return None, None

def check_selection(config, item_name):
	if config and "selection" in config and "type" in config["selection"]:
		if config["selection"]["type"] == "inclusion":
			if "items" not in config["selection"] or type(config["selection"]["items"]) != list:
				return False
			return item_name in config["selection"]["items"]
		elif config["selection"]["type"] == "exclusion":
			if "items" not in config["selection"] or type(config["selection"]["items"]) != list:
				return True
			return item_name not in config["selection"]["items"]
	return True

# ----------------------------------------
#              User input
# ----------------------------------------
def user_confirm(s):
	print(s)
	print(f'Do you want to proceed? [y/n] ', end='')
	while True:
		try:
			return _BOOLMAP[str(input()).lower()]
		except Exception as e:
			print('Please respond with \'y\' or \'n\'.\n')

# ----------------------------------------
# 				Main 
# ----------------------------------------

def process_options():
	parser = optparse.OptionParser()
	parser.set_usage('Usage: %prog [options]')
	parser.add_option('--promotion', '-p', dest='promotion',
						help='Specifies the name of the promotion to run. If not set, all promotions in the configuration will be run. Use --list to see available promotions.')
	parser.add_option('--list', '-l', dest='list', action='store_true',
						help='Prints the list of possible promotions.')
	parser.add_option('--munki', '-m', dest='munki_path', default=MUNKI_PATH,
						help=f'Optional path to the munki pkginfo directory, defaults to {MUNKI_PATH}')
	parser.add_option('--yaml', '-y', dest='config_file',
						help=f'Optional path to the configuration yaml file. Defaults to config.yml if not set. If config.yml does not exist, default configuration will be used.')
	parser.add_option('--slack', '-s', dest='slack_url',
						help=f'Optional url for Slack webhooks.')
	parser.add_option('--markdown', dest='markdown_path',
						help=f'Optional file name to print markdown summary of promotions.')
	parser.add_option('--auto', '-a', dest='auto', action='store_true',
						help='Run without interaction.')
	parser.add_option('--reset-edit-date', dest='reset_edit', action='store_true',
						help='Reset the last edited day of all items to today.')
	parser.add_option('--set-unknown-edit-date', dest='set_edit', action='store_true',
						help='Set all missing last edited days to today.')
	parser.add_option('--days-before-current-catalog', dest='promote_from_days', type='int',
						help='Requires additional command line argument `promotion` to run. For all items that meet the `promote_from` conditions for the given promotion, if the last edit date is unknown it is calculated under the assumption that it took n days to be promoted to the current catalog(s), where n is set by this `days-before-promote-from` argument.')
	options, _ = parser.parse_args()
	# check if slack url in env
	slack_url = options.slack_url
	if (not slack_url) and os.environ.get("SLACK_WEBHOOK"):
		slack_url = os.environ.get("SLACK_WEBHOOK")
	# return based on config file option
	if options.config_file:
		return options.promotion, options.list, options.munki_path, options.config_file, True, slack_url, options.markdown_path, options.auto, options.reset_edit, options.set_edit, options.promote_from_days
	return options.promotion, options.list, options.munki_path, CONFIG_FILE, False, slack_url, options.markdown_path, options.auto, options.reset_edit, options.set_edit, options.promote_from_days

def setup_logging():
	logging.basicConfig(
		level=logging.DEBUG,
		format="%(asctime)s - %(levelname)s (%(module)s): %(message)s",
		datefmt='%d/%m/%Y %H:%M:%S',
		stream=sys.stdout)

def main():
	setup_logging()
	promotion, show_list, munki_path, config_path, is_config_specified, slack_url, md_path, auto, reset_edit, set_edit, promote_from_days = process_options()
	config = get_config(config_path, is_config_specified)

	if reset_edit or set_edit or promote_from_days:
		check_selection_specified_correctly(config, config_path)
		if reset_edit:
			logging.info('Reset the last edited day of all items to today.')
			names, preped_changes = prep_set_edit_date(munki_path, config, overwrite=True)
		elif set_edit:
			logging.info('Setting all missing last edited days to today.')
			names, preped_changes = prep_set_edit_date(munki_path, config)
		elif promote_from_days:
			if not promotion:
				logging.error("Command line argument `days-before-promote-from` must be accompanied by command line argument `promotion` to run, but this is not the case.")
				logging.error("For all items that meet the `promote_from` conditions for the given promotion, if the last edit date is unkown but the creation date is known, the last edit date is calculated under the assumption that it took n days to be promoted to the current catalogue(s), where n is set by this `days-before-promote-from` argument.")
				sys.exit(1)
			else:
				logging.info(f'Setting all missing last edited days for items that meet the `promote_from` conditions for "{promotion}", under the assumption that it took {promote_from_days} days to be promoted to the current catalog(s).')
				names, preped_changes = prep_set_edit_date(munki_path, config, promotion=promotion, promote_from_days=promote_from_days, config_path=config_path)
		if names:
			s = f'The metadata of the following items will be updated: {and_str(names)}'
			if auto or user_confirm(s):
				for preped_change in preped_changes:
					item_path, item = preped_change
					try_add_metadata(item_path, item)
			else:
				logging.info('Ok, aborted..')
		else:
			logging.info("No metadata need to be updated.")

	elif show_list:
		print_promotions(config, config_path)

	elif promotion:
		check_selection_specified_correctly(config, config_path)
		names, versions, custom_item_descriptions, preped_promotions, promote_to = prep_single_promotion(promotion, config, munki_path, config_path)
		if names:
			s = describe_promotion(promotion, promote_to, names, versions, custom_item_descriptions)
			if auto or user_confirm(s):
				# apply changes
				promote_items(preped_promotions)
				# notify about changes
				if slack_url:
					blocks = setup_slack_blocks()
					blocks = add_to_slack_blocks(blocks, promotion, promote_to, names, versions, custom_item_descriptions)
					send_slack_webhook(slack_url, blocks)
				if md_path:
					md = md_description(promotion, promote_to, names, versions, custom_item_descriptions)
					write_md_file(md_path, md)
			else:
				logging.info('Ok, aborted..')
		else:
			logging.info("No items need to be promoted.")

	else:
		check_selection_specified_correctly(config, config_path)
		names_dict, versions_dict, custom_item_descriptions_dict, preped_promotions, promote_tos = prep_all_promotions(config, munki_path, config_path)
		if len(names_dict) > 0:
			s = ""
			for promotion in config["promotions"]: # present promotions in order of config file
				if promotion in names_dict:
					s += describe_promotion(promotion, promote_tos[promotion], names_dict[promotion], versions_dict[promotion], custom_item_descriptions_dict[promotion])
			if auto or user_confirm(s):
				# apply changes
				promote_items(preped_promotions)
				# notify about changes
				if slack_url:
					blocks = setup_slack_blocks()
					for promotion in config["promotions"]: # present promotions in order of config file
						if promotion in names_dict:
							blocks = add_to_slack_blocks(blocks, promotion, promote_tos[promotion], names_dict[promotion], versions_dict[promotion], custom_item_descriptions_dict[promotion])
					send_slack_webhook(slack_url, blocks)
				if md_path:
					md = ""
					for promotion in config["promotions"]: # present promotions in order of config file
						if promotion in names_dict:
							md += md_description(promotion, promote_tos[promotion], names_dict[promotion], versions_dict[promotion], custom_item_descriptions_dict[promotion])
					write_md_file(md_path, md)
			else:
				logging.info('Ok, aborted..')
		else:
			logging.info("No items need to be promoted.")

if __name__ == '__main__':
	main()
