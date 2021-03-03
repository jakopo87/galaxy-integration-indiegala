# galaxy-integration-indiegala

GOG Galaxy Integration for Indiegala Showcase (https://www.indiegala.com/library/showcase)


## Installation

1. Download [latest release](https://github.com/jakopo87/galaxy-integration-indiegala) of the plugin for your platform.
2. Create plugin folder:

- Windows: `%LOCALAPPDATA%\GOG.com\Galaxy\plugins\installed\<my-plugin-name>`
- MacOS: `${HOME}/Library/Application Support/GOG.com/Galaxy/plugins/installed/<my-plugin-name>`

3. Unpack downloaded release to created folder.
4. Restart GOG Galaxy Client.

## Issue reporting
Along with you detailed problem description, you may need to attach plugin log files located at:
- Windows: `%programdata%\GOG.com\Galaxy\logs`
- MacOS: `/Users/Shared/GOG.com/Galaxy/Logs`

for example:
`C:\ProgramData\GOG.com\Galaxy\logs\plugin-indiegala-36acb84a-5b49-4e2b-bb17-ac9f082f62b0.log`

## Development

Run `deploy.ps1` to create the plugin content and install with its dependencies directly inside gog plugin folder, a folder named `indiegala-showcase` will be created, if it already exists its content will be overwritten.
