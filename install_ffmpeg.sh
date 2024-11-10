#!/bin/bash
# install_ffmpeg.sh - This script installs FFmpeg on Heroku during deployment

echo "Starting FFmpeg installation..."

# Download FFmpeg binaries from an official source
curl -sSL https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-i686-static.tar.xz -o ffmpeg.tar.xz

# Check if the download was successful
if [ $? -ne 0 ]; then
  echo "Failed to download FFmpeg."
  exit 1
fi

# Extract the archive
tar -xf ffmpeg.tar.xz

# Check if the extraction was successful
if [ $? -ne 0 ]; then
  echo "Failed to extract FFmpeg archive."
  exit 1
fi

# Move the binaries to /usr/local/bin (this is the directory where Heroku looks for executables)
mv ffmpeg*/ffmpeg /usr/local/bin/
mv ffmpeg*/ffprop /usr/local/bin/

# Clean up the downloaded files
rm -rf ffmpeg*

echo "FFmpeg installation completed successfully."
