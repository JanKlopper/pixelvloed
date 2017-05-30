#!/usr/bin/python
"""This is an udp / binary client

Inspired by the PixelFlut projector on eth0:winter 2016 and
code from https://github.com/defnull/pixelflut/
"""

__version__ = 0.3
__author__ = "Jan Klopper <jan@underdark.nl>"

import random
from vloed import PixelVloedClient, InitMessage, RGBPixel, MAX_PIXELS

def RandomFill(pixels, width, height):
  """Generates a random number of pixels with a random color"""
  for pixel in xrange(0, random.randint(10, MAX_PIXELS)):
    pixel = RGBPixel(random.randint(0, width),
                     random.randint(0, height),
                     random.randint(0, 255),
                     random.randint(0, 255),
                     random.randint(0, 255))
    pixels.append(pixel)

def RunClient(options):
  """Discover the servers and start sending to the first one"""

  client = PixelVloedClient(True, # start as soon as we find a server
                            options.debug, # show debugging output
                            options.ip, # ip of the server, None for autodetect
                            options.port, # port of the server None for autodetect
                            options.width, # Screen pixels wide, None for autodetect
                            options.height  # Screen pixels height, None for autodetect
                            )

  # loop the effect until we cancel by pressing ctrl+c / exit the program
  while True:
    pixels = [] # list to store the pixels we want to send

    # add some pixels to the output with our functions
    # the width/height are read from the client's config
    RandomFill(pixels, client.width, client.height)

    # send our pixels in packets including a message header and less than
    # MAX_PIXELS pixels
    for part in SplitList(MAX_PIXELS, pixels):
      packet = InitMessage([]) + part
      client.SendPacket(''.join(packet))

def SplitList(max_size, lis):
    """Splits a list into equal-sized chunks"""
    for i in xrange(0, len(lis), max_size):
        yield lis[i:i+max_size]

if __name__ == '__main__':
  # if this script is called from the command line, and thus not imported
  # start a client and start sending messages
  import optparse
  parser = optparse.OptionParser()
  parser.add_option('-v', action="store_true", dest="debug", default=False)
  parser.add_option('-i', action="store", dest="ip", default=None)
  parser.add_option('-p', action="store", dest="port", default=None,
                    type="int")
  parser.add_option('-x', action="store", dest="width", default=None,
                    type="int")
  parser.add_option('-y', action="store", dest="height", default=None,
                    type="int")
  options, remainder = parser.parse_args()

  try:
    RunClient(options)
  except KeyboardInterrupt:
    print 'Closing client'
