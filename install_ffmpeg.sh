#!/bin/bash
# Install FFmpeg

echo "Installing FFmpeg..."

# Download and install FFmpeg (you can change the version if necessary)
curl -sSL https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-i686-static.tar.xz -o ffmpeg.tar.xz
tar -xf ffmpeg.tar.xz
mv ffmpeg*/ffmpeg /usr/local/bin/
mv ffmpeg*/ffprop /usr/local/bin/

# Clean up
rm -rf ffmpeg*

echo "FFmpeg installation complete"
