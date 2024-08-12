# munki-promoter
`munki-promoter` is a rule-based tool for promoting Munki items between catalogs which, when used with CI, can automate Munki promotions for you. 

You can read more about `munki-promoter` [here](https://jc0b.computer/posts/munki-promoter-automatic-munki).

## Getting started
To get started with `munki-promoter`, you should read the ["Getting Started" page](https://github.com/jc0b/munki-promoter/wiki/Home) in the wiki.

Information about configuring `munki-promoter` can be found in [the configuration documentation](https://github.com/jc0b/munki-promoter/wiki/Supported-Configuration-Keys). [Examples](https://github.com/jc0b/munki-promoter/wiki/Example-Configurations) are also provided.

> [!WARNING]
> When running `munki-promoter` (versions 2.0 and later) for the first time, you will notice that the first run against your repo may attempt to promote things that shouldn't be eligible for promotion yet.
> This is due to `munki-promoter` not "knowing" how long an item has been in a catalog beyond its initial import date.
> You can work around this by using one of the following provided [Command-line Arguments](Command-line-Arguments):
> `--reset-edit-date`, `--set-unknown-edit-date`, `--days-before-current-catalog`
> 
> The smoothest option if you have static promotion rules is to use `--days-before-current-catalog`. If you know items get promoted to staging 7 days after creation, this command can infer that items in staging have been "last edited" 7 days after creation.
