# MikroTik upgrade

A Python script for updating multiple MikroTik RouterOS devices via SSH. It is designed to be a conservative as possible so as to have the lowest possible chance of leaving your network broken.

# Project goals

* Upgrade RouterOS devices without needing them to have Internet access. This also has the advantage of only having to download updates once per CPU architecture.
* Fail on ALL unexpected results. So if something goes wrong updating one device it will stop hopefully leaving all further devices still functioning.
* Safely automated. It should be as safe as possible to have this set to run automatically and in the event of a problem at most one device should be left with an issue (barring config changes across versions).


### Prerequisites

fping is required to check for whether the device is online.

Some code will require Python 3. Running it with Python 2.7 might be possible with some code changes but some libraries might be a problem.

Some extra Python libraries are also required:
* paramiko
* scp
* packaging
* urllib (if getting the script to download the packages for you)

On Debian / Ubuntu based systems these are all installable with:
```
sudo aptitude install python3-urllib3 python3-paramiko python3-scp python3-packaging fping
```

## Contributing

All contributions, ideas and criticism is welcome. :-)

## Authors

* **Andrew Radke**

## License

This project is licensed under the GNU General Public License Version 3 available at https://www.gnu.org/licenses/gpl-3.0.en.html
