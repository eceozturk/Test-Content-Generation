import sys, os, glob, getopt
from pathlib import Path
from enum import Enum
import subprocess
from subprocess import PIPE
from datetime import datetime
import struct
from xml.dom.minidom import parse
import xml.dom.minidom


# Content Model
# Modify the generated content to comply with CTA Content Model
class Mode(Enum):
    FRAGMENTED = 1
    CHUNKED = 2

class ContentModel:
    m_filename = ""
    m_mode = Mode.FRAGMENTED.value

    def __init__(self, filename, mode=None):
        self.m_filename = filename
        if mode is not None:
            self.m_mode = mode

    def process(self):
        DOMTree = xml.dom.minidom.parse(self.m_filename)
        mpd = DOMTree.documentElement
        self.process_mpd(DOMTree, mpd)
        with open(self.m_filename, 'w') as f:
            f.write(DOMTree.toxml())

    def process_mpd(self, DOMTree, mpd):
        # @profiles
        profiles = mpd.getAttribute('profiles')
        cta_profile = "urn:cta:wave:test-content-media-profile"
        fragmented_profile = "urn:mpeg:dash:profile:isoff-live:2011"
        chunked_profile = "urn:mpeg:dash:profile:isoff-broadcast:2015"
        if cta_profile not in profiles:
            profiles += "," + cta_profile
        if self.m_mode is Mode.FRAGMENTED.value and fragmented_profile not in profiles:
            profiles += "," + fragmented_profile
        if self.m_mode is Mode.CHUNKED.value and chunked_profile not in profiles:
            profiles += "," + chunked_profile
        mpd.setAttribute('profiles', profiles)

        # Remove ServiceDescrition element if present (somehow ffmpeg 4.3 adds this to the mpd by default, removed for now)
        service_descriptions = mpd.getElementsByTagName("ServiceDescription")
        self.remove_element(service_descriptions)

        # ProgramInformation
        program_informations = mpd.getElementsByTagName("ProgramInformation")
        self.remove_element(program_informations)
        program_information = DOMTree.createElement("ProgramInformation")
        source = DOMTree.createElement("Source")
        source_txt = DOMTree.createTextNode("CTA WAVE")
        source.appendChild(source_txt)
        copyright = DOMTree.createElement("Copyright")
        copyright_txt = DOMTree.createTextNode("CTA WAVE")
        copyright.appendChild(copyright_txt)
        program_information.appendChild(source)
        program_information.appendChild(copyright)

        # Period
        period = mpd.getElementsByTagName("Period").item(0)
        mpd.insertBefore(program_information, period)
        self.process_period(DOMTree, mpd, period)

    def process_period(self, DOMTree, mpd, period):
        asset_identifier = DOMTree.createElement("AssetIdentifier")
        asset_identifier.setAttribute("schemeIdUri", "urn:cta:org:wave-test-mezzanine:unique-id")
        asset_identifier.setAttribute("value", "0")
        adaptation_sets = period.getElementsByTagName("AdaptationSet")
        period.insertBefore(asset_identifier, adaptation_sets.item(0))
        # Adaptation Set
        self.process_adaptation_sets(period.getElementsByTagName('AdaptationSet'))

    def process_adaptation_sets(self, adaptation_sets):
        adaptation_set_index = 0
        representation_index = 0
        for adaptation_set in adaptation_sets:
            id = adaptation_set.getAttribute('id')

            content_type = adaptation_set.getAttribute('contentType')
            if  content_type == "":
                representations = adaptation_set.getElementsByTagName('Representation')
                mime_type = representations.item(0).getAttribute('mimeType') if representations.item(0).getAttribute('mimeType') != '' \
                    else adaptation_set.getAttribte('mimeType')

                if 'video' in mime_type:
                    content_type = 'video'
                    adaptation_set.setAttribute('contentType', content_type)
                elif 'audio' in mime_type:
                    content_type = 'audio'
                    adaptation_set.setAttribute('contentType', content_type)

            if self.m_mode == Mode.FRAGMENTED.value:
                adaptation_set.setAttribute('segmentProfiles', 'cmfs, cmff')
            elif self.m_mode == Mode.CHUNKED.value:
                adaptation_set.setAttribute('segmentProfiles', 'cmfs, cmff, cmfl')

            representations = adaptation_set.getElementsByTagName('Representation')
            for representation in representations:
                # Representation
                self.process_representation(representation, adaptation_set_index, representation_index, id, content_type)
                representation_index += 1

            adaptation_set_index += 1

    def process_representation(self, representation, adaptation_set_index, representation_index, id, content_type):
        rep_id = content_type + id + "/" + str(representation_index)

        rep_path = "./" + rep_id
        Path(rep_path).mkdir(parents=True, exist_ok=True)

        init_name = "init-stream" + str(representation_index)
        os.rename(init_name + ".m4s", rep_id + "/0.m4s")

        media_name = "chunk-stream" + str(representation_index)
        files = subprocess.run("ls -v | grep '" + media_name + "'", shell=True, stdout=PIPE, stderr=PIPE).stdout.decode('ascii').split("\n")
        number = 1
        for file in files:
            if file != '':
                os.rename(file, rep_id + "/" + str(number) + ".m4s")
                number += 1
        representation.setAttribute('id', rep_id)

        mime_type = representation.getAttribute('mimeType')
        representation.setAttribute('mimeType', mime_type + ", profiles='cmfc'")

        segment_template = representation.getElementsByTagName('SegmentTemplate').item(0)
        segment_template.setAttribute('initialization', '$RepresentationID$/0.m4s')
        segment_template.setAttribute('media', '$RepresentationID$/$Number$.m4s')


    def remove_element(self, nodes):
        for node in nodes:
            parent = node.parentNode
            parent.removeChild(node)


# Supported codecs
class VideoCodecOptions(Enum):
    AVC = "h264"
    HEVC = "h265"


class AudioCodecOptions(Enum):
    AAC = "aac"


# CMAF Profiles
# ISO/IEC 23000-19 Annex A.1
class AVCSD:
    m_profile = "high"
    m_level = "31"
    m_color_primary = "1"
    m_resolution_w = "864"
    m_resolution_h = "576"
    m_frame_rate = "60"


class AVCHD:
    m_profile = "high"
    m_level = "40"
    m_color_primary = "1"
    m_resolution_w = "1920"
    m_resolution_h = "1080"
    m_frame_rate = "60"


class AVCHDHF:
    m_profile = "high"
    m_level = "42"
    m_color_primary = "1"
    m_resolution_w = "1920"
    m_resolution_h = "1080"
    m_frame_rate = "60"

# DASHing
# ffmpeg command dashing portion
class DASH:
    m_segment_duration = "2"
    m_segment_signaling = "timeline"

    def __init__(self, dash_config=None):
        if dash_config is not None:
            config = dash_config.split(',')
            for i in range(0, len(config)):
                config_opt = config[i].split(":")
                name = config_opt[0]
                value = config_opt[1]

                if name == "d":
                    self.m_segment_duration = value
                elif name == "s":
                    if value != "template" and value != "timeline":
                        print("Segment Signaling can either be Segment Template denoted by \"template or "
                              "SegmentTemplate with Segment Timeline denoted by \"timeline\".")
                        exit(1)
                    else:
                        self.m_segment_signaling = value

    def dash_package_command(self, index_v, index_a):
        dash_command = "-adaptation_sets "
        if index_v > 0 and index_a>0:
            dash_command += "\"id=0,streams=v id=1,streams=a\" "
        elif index_v > 0 and index_a == 0:
            dash_command += "\"id=0,streams=v\" "
        elif index_v == 0 and index_a > 0:
            dash_command += "\"id=0,streams=a\" "
        else:
            print("At least one Represetation must be provided to be DASHed")
            sys.exit(1)

        dash_command += "-format_options \"movflags=cmaf\" " + \
                  "-seg_duration " + self.m_segment_duration + " " + \
                  "-use_template 1 "
        if self.m_segment_signaling is "timeline":
            dash_command += "-use_timeline 1 "
        else:
            dash_command += "-use_timeline 0 "

        dash_command += "-f dash"

        return dash_command


# Encoding
# ffmpeg command encoding portion for each track. Encoding is done based on the representation configuration given in
# the command line. The syntax for configuration for each Representation is as follows:
#### rep_config = <config_parameter_1>:<config_parameter_value_1>,<config_parameter_2>:<config_parameter_value_2>,…
# <config_parameter> can be:
#### id: Representation ID
#### type: Media type. Can be “v” or “video” for video media and “a” or “audio” for audio media type
#### input: Input file name. The media type mentioned in “type” will be extracted from this input file for the Representation
#### codec: codec value for the media. Can be “h264”, “h265” or “aac”
#### bitrate: encoding bitrate for the media in kbits/s
#### cmaf: cmaf profile that is desired. Supported ones are avcsd, avchd, avchdhf (taken from 23000-19 A.1)
#### res: resolution width and resolution height provided as “wxh”
#### fps: framerate
#### sar: aspect ratio provided as “x/y”
#### profile: codec profile (such as high, baseline, main, etc.)
#### level: codec level (such as 32, 40, 42, etc.)
#### color: color primary (1 for bt709, etc.)
# The first six configuration parameters are mandatory to be provided. The rest can be filled according to the specified
# cmaf profile. If the rest is also given, these will override the default values for the specified CMAF profile
class Representation:
    m_id = None
    m_input = None
    m_media_type = None
    m_codec = None
    m_cmaf_profile = None
    m_bitrate = None
    m_resolution_w = None
    m_resolution_h = None
    m_frame_rate = None
    m_aspect_ratio_x = None
    m_aspect_ratio_y = None
    m_profile = None
    m_level = None
    m_color_primary = None

    def __init__(self, representation_config):
        config = representation_config.split(",")
        for i in range(0, len(config)):
            config_opt = config[i].split(":")
            name = config_opt[0]
            value = config_opt[1]

            if name == "id":
                self.m_id = value
            elif name == "input":
                self.m_input = value
            elif name == "type":
                self.m_media_type = value
            elif name == "codec":
                if value != VideoCodecOptions.AVC.value and value != VideoCodecOptions.HEVC.value and value != AudioCodecOptions.AAC.value:
                    print("Supported codecs are AVC denoted by \"h264\" and HEVC denoted by \"h265\" for video and"
                          "AAC denoted by \"aac\".")
                    sys.exit(1)
                self.m_codec = value
            elif name == "cmaf":
                self.m_cmaf_profile = value
                if value == "avcsd":
                    if self.m_profile is None:
                        self.m_profile = AVCSD.m_profile
                    if self.m_level is None:
                        self.m_level = AVCSD.m_level
                    if self.m_frame_rate is None:
                        self.m_frame_rate = AVCSD.m_frame_rate
                    if self.m_color_primary is None:
                        self.m_color_primary = AVCSD.m_color_primary
                    if self.m_resolution_w is None and self.m_resolution_h is None:
                        self.m_resolution_w = AVCSD.m_resolution_w
                        self.m_resolution_h = AVCSD.m_resolution_h
                elif value == "avchd":
                    if self.m_profile is None:
                        self.m_profile = AVCHD.m_profile
                    if self.m_level is None:
                        self.m_level = AVCHD.m_level
                    if self.m_frame_rate is None:
                        self.m_frame_rate = AVCHD.m_frame_rate
                    if self.m_color_primary is None:
                        self.m_color_primary = AVCHD.m_color_primary
                    if self.m_resolution_w is None and self.m_resolution_h is None:
                        self.m_resolution_w = AVCHD.m_resolution_w
                        self.m_resolution_h = AVCHD.m_resolution_h
                elif value == "avchdhf":
                    if self.m_profile is None:
                        self.m_profile = AVCHDHF.m_profile
                    if self.m_level is None:
                        self.m_level = AVCHDHF.m_level
                    if self.m_frame_rate is None:
                        self.m_frame_rate = AVCHDHF.m_frame_rate
                    if self.m_color_primary is None:
                        self.m_color_primary = AVCHDHF.m_color_primary
                    if self.m_resolution_w is None and self.m_resolution_h is None:
                        self.m_resolution_w = AVCHDHF.m_resolution_w
                        self.m_resolution_h = AVCHDHF.m_resolution_h
            elif name == "bitrate":
                self.m_bitrate = value
            elif name == "res":
                resolution_w_h = value.split('x')
                self.m_resolution_w = resolution_w_h[0]
                self.m_resolution_h = resolution_w_h[1]
            elif name == "fps":
                self.m_frame_rate = value
            elif name == "sar":
                sar_x_y = value.split(':')
                self.m_aspect_ratio_x = sar_x_y[0]
                self.m_aspect_ratio_y = sar_x_y[1]
            elif name == "profile":
                self.m_profile = value
            elif name == "level":
                self.m_level = value
            elif name == "color":
                self.m_color_primary = value
            else:
                print("Unknown configuration option for representation: " + name + " , it will be ignored.")

        if self.m_id is None or self.m_input is None or self.m_media_type is None or self.m_codec is None or \
           self.m_bitrate is None or self.m_cmaf_profile is None:
            print("For each representation at least the following 6 parameters must be provided: " +
                  "<representation_id>,<input_file>,<media_type>,<codec>,<bitrate>,<cmaf_profile>")
            sys.exit(1)

    def form_command(self, index):
        input_file_command = "-i " + self.m_input
        command = ""

        if self.m_media_type in ("v", "video"):
            command += "-map " + index + ":v:0" + " " \
                       "-c:v:" + index + " " + self.m_codec + " " + \
                       "-b:v:" + index + " " + self.m_bitrate + "k " + \
                       "-s:v:" + index + " " + self.m_resolution_w + "x" + self.m_resolution_h + " " + \
                       "-r:v:" + index + " " + self.m_frame_rate + " " + \
                       "-profile:v:" + index + " " + self.m_profile + " " + \
                       "-color_primaries:v:" + index + " " + self.m_color_primary + " " + \
                       "-color_trc:v:" + index + " " + self.m_color_primary + " " + \
                       "-colorspace:v:" + index + " " + self.m_color_primary + " "
            if self.m_aspect_ratio_x is not None and self.m_aspect_ratio_y is not None:
                command += "-vf:v:" + index + " " + "\"setsar=" + self.m_aspect_ratio_x + "/" + self.m_aspect_ratio_y + "\" "

            if self.m_codec == VideoCodecOptions.AVC.value:
                command += "-x264-params:v:" + index + " "
            elif self.m_codec == VideoCodecOptions.HEVC.value:
                command += "-x265-params:v:" + index + " "

            command += "level=" + self.m_level + ":" \
                       "no-open-gop=1" + ":" \
                       "min-keyint=" + self.m_frame_rate + ":" \
                       "keyint=" + self.m_frame_rate + ":" \
                       "scenecut=0"

        elif self.m_media_type in ("a", "audio"):
            command += "-map " + index + ":a:0" + " " \
                       "-c:a:" + index + " " + self.m_codec + " " + \
                       "-b:a:" + index + " " + self.m_bitrate + "k"

        return [input_file_command, command]

# Collect logs regarding the generated content. The collected logs are as follows:
#### Content generation date and time,
#### ffmpeg version,
#### ffmpeg command that is run,
#### this python script (encode_dash.py)
def generate_log(ffmpeg_path, command):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date = now.split(" ")[0]
    time = now.split(" ")[1]

    result = subprocess.run(ffmpeg_path + " -version", shell=True, stdout=PIPE, stderr=PIPE)

    script = ""
    with open('encode_dash.py', 'r') as file:
        script = file.read()

    filename = "CTATestContentGeneration_Log_" + date + "_" + time
    f = open(filename, "w+")

    f.write("CTA Test Content Generation Log (Generated at: " + "'{0}' '{1}'".format(date, time) + ")\n\n\n\n")

    f.write("-----------------------------------\n")
    f.write("FFMPEG Information:\n")
    f.write("-----------------------------------\n")
    f.write("%s\n\n\n\n" % result.stdout.decode('ascii'))

    f.write("-----------------------------------\n")
    f.write("Command run:\n")
    f.write("-----------------------------------\n")
    f.write("%s\n\n\n\n" % command)

    f.write("-----------------------------------\n")
    f.write("Encode.py:\n")
    f.write("-----------------------------------\n")
    f.write("%s\n\n\n\n" % script)
    f.close()


# Parse input arguments
# Output MPD: --out="<desired_mpd_name>"
# FFMpeg binary path: -–path="path/to/ffmpeg"
# Representation configuration: --reps="<rep1_config rep2_config … repN_config>"
# DASHing configuration: --dash="<dash_config>"
def parse_args(args):
    ffmpeg_path = None
    output_file = None
    representations = None
    dashing = None
    for opt, arg in args:
        if opt == '-h':
            print('test.py -i <inputfile> -o <outputfile>')
            sys.exit()
        elif opt in ("-p", "--path"):
            ffmpeg_path = arg
        elif opt in ("-o", "--out"):
            output_file = arg
        elif opt in ("-r", "--reps"):
            representations = arg.split(" ")
        elif opt in ("-d", "--dash"):
            dashing = arg

    return [ffmpeg_path, output_file, representations, dashing]


# Check if the input arguments are correctly given
def assert_configuration(configuration):
    ffmpeg_path = configuration[0]
    output_file = configuration[1]
    representations = configuration[2]
    dashing = configuration[3]

    result = subprocess.run(ffmpeg_path + " -version", shell=True, stdout=PIPE, stderr=PIPE)
    if "ffmpeg version" not in result.stdout.decode('ascii'):
        print("FFMPEG binary is checked in the \"" + ffmpeg_path + "\" path, but not found.")
        sys.exit(1)

    if output_file is None:
        print("Output file name must be provided")
        sys.exit(1)

    if representations is None:
        print("Representations description must be provided.")
        sys.exit(1)

    if dashing is None:
        print("Warning: DASHing information is not provided, as a default setting, segment duration of 2 seconds and "
              "segment signaling of SegmentTemplate will be used.")


if __name__ == "__main__":
    # Read input, parse and assert
    try:
        arguments, values = getopt.getopt(sys.argv[1:], 'ho:r:d:p', ['out=', 'reps=', 'dash=', 'path='])
    except getopt.GetoptError:
        sys.exit(2)

    configuration = parse_args(arguments)
    assert_configuration(configuration)

    ffmpeg_path = configuration[0]
    output_file = configuration[1]
    representations = configuration[2]
    dash = configuration[3]

    # Prepare the encoding for each Representation
    options = []
    index_v = 0
    index_a = 0
    for representation_config in representations:
        representation = Representation(representation_config)
        if representation.m_media_type in ("v", "video"):
            options.append(representation.form_command(str(index_v)))
            index_v += 1
        elif representation.m_media_type in ("a", "audio"):
            options.append(representation.form_command(str(index_a)))
            index_a += 1
        else:
            print("Media type for a representation denoted by <type> can either be \"v\" or \"video\" fro video media"
                  "or \"a\" or \"audio\" for audio media.")
            exit(1)

    input_command = ""
    encode_command = ""
    for i in range(0, len(options)):
        option_i = options[i]
        input_command += option_i[0] + " "
        encode_command += option_i[1] + " "

    # Prepare the DASH formatting
    dash_options = DASH(dash)
    dash_package_command = dash_options.dash_package_command(index_v, index_a)

    # Run the command
    command = ffmpeg_path + " " + \
              input_command + " " + \
              encode_command + " " + \
              dash_package_command + " " + \
              output_file

    subprocess.run(command, shell=True)

    # Content Model
    content_model = ContentModel(output_file)
    content_model.process()

    # Save the log
    generate_log(ffmpeg_path, command)
