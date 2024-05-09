# munki-promoter
`munki-promoter` is a tool for promoting Munki items between catalogs which, when used with CI, can automate Munki promotions for you. You will probably need to fork it and modify it to work with an existing Munki environment.

You can read more about munki-promoter [here](https://jc0b.computer/posts/munki-promoter-automatic-munki).

## Usage
`munki-promoter` contains a few default promotions. You can list these with `./munki-promoter.py --list`.

Then, you can run the migration you want with `./munki-promoter.py --name=<migration_name>`.
