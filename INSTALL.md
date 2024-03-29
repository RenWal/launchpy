# Prerequisites
Prior to installation, please install the [dependencies](https://spotlightkid.github.io/python-rtmidi/installation.html#linux) needed to compile python-rtmidi (which is part of the `requirements.txt`).

# Install
```sh
git clone git@github.com:RenWal/launchpy.git
cd launchpy
# set up virtual environment
python3 -m venv env
source env/bin/activate
# install base dependencies
pip install -U pip
pip install wheel
pip install -r requirements.txt
# if needed, install dependencies of your desired plugins:
pip install -r additional_requirements{...}.txt
```

# Configuration
Open `settings.py`. You'll see the `APC_PORT` and `PLUGINS`. In the
former, you can paste the MIDI identifier (see above) to select a special
device. If you only have a single APC connected, you don't need to set this.
In the latter, you can pick the plugins that you want to use. By default,
there are two plugins `PulsePlugin` and `GnomeWorkspacePlugin`. There is also
a demo plugin that you can use to play around with the APC and test if all
your buttons are working. If you want do disable any plugin, just comment its
entry out.

# Run
Just execute `./launch.py` in your virtual environment.

# As a `systemd` service
If you wish, you can schedule LaunchPy to run as a user service on `systemd`.
Create the directory `~/.config/systemd/user`, copy `service/launchpy.service`
from this repository to that directory and update the paths at the marked spots
in this service file.

You can then enable and start the service:
```sh
systemctl --user daemon-reload
systemctl --user enable launchpy.service
systemctl --user start launchpy.service
```
