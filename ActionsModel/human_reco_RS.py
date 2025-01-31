from __future__ import print_function
import sys
import os
from argparse import ArgumentParser, SUPPRESS
import cv2
import time
import logging as log
import numpy as np
import imutils

from openvino.inference_engine import IENetwork, IEPlugin, IECore
import pyrealsense2 as rs

#To send posts
import requests
url = 'http://10.22.172.26'
header={"Content-Length":"18","Content-Type":"application/json","Cache-Control":"no-cache","Host":"10.22.172.26"}
objToServer = {'result':'alert'}

cam_id = "cam1"

def build_argparser():
    parser = ArgumentParser(add_help=False)
    args = parser.add_argument_group('Options')
    args.add_argument('-h', '--help', action='help', default=SUPPRESS, help='Show this help message and exit.')
    args.add_argument("-m", "--model", help="Required. Path to an .xml file with a trained model.",
                      required=True, type=str)
    args.add_argument("-i", "--input",
                      help="Required. Path to video file or image. 'cam' for capturing video stream from camera",
                      required=True, type=str)
    args.add_argument("-l", "--cpu_extension",
                      help="Optional. Required for CPU custom layers. Absolute path to a shared library with the "
                           "kernels implementations.", type=str, default=None)
    args.add_argument("-d", "--device",
                      help="Optional. Specify the target device to infer on; CPU, GPU, FPGA, HDDL or MYRIAD is "
                           "acceptable. The demo will look for a suitable plugin for device specified. "
                           "Default value is CPU", default="CPU", type=str)
    args.add_argument("--labels", help="Optional. Path to labels mapping file", default=None, type=str)
    args.add_argument("-pt", "--prob_threshold", help="Optional. Probability threshold for detections filtering",
                      default=0.5, type=float)

    return parser


args = build_argparser().parse_args()
SAMPLE_SIZE = 112

model_xml=args.model
model_bin=os.path.splitext(model_xml)[0] + ".bin"

ie = IECore()


if args.cpu_extension and 'CPU' in args.device:
        ie.add_extension(args.cpu_extension, "CPU")


net=IENetwork(model=model_xml, weights=model_bin)

#Special CPU settings
if "CPU" in args.device:
        supported_layers = ie.query_network(net, "CPU")
        not_supported_layers = [l for l in net.layers.keys() if l not in supported_layers]
        if len(not_supported_layers) != 0:
            log.error("Following layers are not supported by the plugin for specified device {}:\n {}".
                      format(args.device, ', '.join(not_supported_layers)))
            log.error("Please try to specify cpu extensions library path in sample's command line parameters using -l "
                      "or --cpu_extension command line argument")
            sys.exit(1)





input_blob = None
out_blob=None
feed_dict = {}
#Getting input and output layer
for l in net.inputs:
    input_blob = l

for l in net.outputs:
    out_blob=l

#Load network to api
exec_net = ie.load_network(network=net, num_requests=2, device_name=args.device)
#Get input layer shape
e, n, c, h, w = net.inputs[input_blob].shape

#Setting input

if args.input == 'cam':
        input_stream = 0
        print("Running on cam")
else:
        input_stream = args.input
        assert os.path.isfile(args.input), "Specified input file doesn't exist"
if args.labels:
        with open(args.labels, 'r') as f:
            labels_map = [x.strip() for x in f]
else:
        labels_map = None

# RealSense initial configuration
print("Real Sense initial configuration")
pipeline = rs.pipeline()
config = rs.config()
config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)

# Start streaming
pipeline.start(config)

frames_pipe = pipeline.wait_for_frames()
color_frame = frames_pipe.get_color_frame()
color_image = np.asanyarray(color_frame.get_data())
frame = color_image

#cap = cv2.VideoCapture(input_stream)

cur_request_id = 0
next_request_id = 1
log.info("Starting inference in async mode...")
is_async_mode = True
render_time = 0
#ret, frame = cap.read()
frames=[]


for i in range (c-1):
    frames_pipe = pipeline.wait_for_frames()
    color_frame = frames_pipe.get_color_frame()
    color_image = np.asanyarray(color_frame.get_data())
    next_frame = color_image
    #ret, next_frame = cap.read()
    next_frame = imutils.resize(next_frame, width=400)
    frames.append(next_frame)
    frame = next_frame
    key = cv2.waitKey(1)



#while cap.isOpened():
while True:   
    frames_pipe = pipeline.wait_for_frames()
    color_frame = frames_pipe.get_color_frame()
    color_image = np.asanyarray(color_frame.get_data())
    
    next_frame = color_image
    
    """
    if is_async_mode:
        ret, next_frame = cap.read()
    else:
        ret, frame = cap.read()
    if not ret:
        break
    initial_w = cap.get(3)
    initial_h = cap.get(4)
    """

    inf_start = time.time()

    if is_async_mode or not is_async_mode:                  #Mandatory async
        next_frame = imutils.resize(next_frame, width=400)
        frames.append(next_frame)
        blob = cv2.dnn.blobFromImages(frames, 1.0,
                    (SAMPLE_SIZE, SAMPLE_SIZE), (114.7748, 107.7354, 99.4750),
                    swapRB=True, crop=True)
        blob = np.transpose(blob, (1, 0, 2, 3))
        in_frame = np.expand_dims(blob, axis=0)
        #in_frame = cv2.resize(next_frame, (w, h))
        #in_frame = in_frame.transpose((2, 0, 1))  # Change data layout from HWC to CHW
        #in_frame = in_frame.reshape(( e, n, c, h, w))
        feed_dict[input_blob] = in_frame
        exec_net.start_async(request_id=next_request_id, inputs=feed_dict)

    if exec_net.requests[cur_request_id].wait(-1) == 0:
        inf_end = time.time()
        det_time = inf_end - inf_start

        # Parse detection results of the current request
        res = exec_net.requests[cur_request_id].outputs[out_blob]
        res=res.reshape((400))
        obj=np.argmax(res)
        
        det_label = labels_map[obj] if labels_map else str(obj)

        if (res[obj] > args.prob_threshold) and ((det_label == "pushing car") 
                                            or (det_label == "unloading truck")
                                            or (det_label == "pumping gas")
                                            or (det_label == "changing wheel")
                                            or (det_label == "cleaning gutters")
                                            or (det_label == "building shed")):
            
            #print(det_label + " " + str(res[obj]))
            print("Action detected... " + str(res[obj]))
            cv2.putText(frame, str(det_label) + ' ' , (15, 50),
                                    cv2.FONT_HERSHEY_COMPLEX, 0.6, 255, 1)
            
            # Send found result to server
            try:
                objToServer["label"]= det_label
                objToServer["cam_id"]= cam_id
                finalLength=len(objToServer["label"]) + len(objToServer["cam_id"])+18
                header["Content-Length"]=str(finalLength)
                requestSent = requests.post(url, data = objToServer, headers=header)
                alreadySent=True
                print(requestSent.text)
            except:
                print ("Could not send alert to server")


        # Draw performance stats
        inf_time_message = "Inference time: N\A for async mode" if is_async_mode else \
            "Inference time: {:.3f} ms".format(det_time * 1000)
        render_time_message = "OpenCV rendering time: {:.3f} ms".format(render_time * 1000)
        async_mode_message = "Async mode is on. Processing request {}".format(cur_request_id) if is_async_mode else \
            "Async mode is off. Processing request {}".format(cur_request_id)

        """
        cv2.putText(frame, inf_time_message, (15, 15), cv2.FONT_HERSHEY_COMPLEX, 0.5, (200, 10, 10), 1)
        cv2.putText(frame, render_time_message, (15, 30), cv2.FONT_HERSHEY_COMPLEX, 0.5, (10, 10, 200), 1)
        cv2.putText(frame, async_mode_message, (10, int(initial_h - 20)), cv2.FONT_HERSHEY_COMPLEX, 0.5,
                    (10, 10, 200), 1)
        """
    

    #Show results
    render_start = time.time()
    cv2.imshow("Action Detection Camera", frame)
    render_end = time.time()
    render_time = render_end - render_start
    #Get next frame
    if is_async_mode:
        cur_request_id, next_request_id = next_request_id, cur_request_id
        frame = next_frame
    key = cv2.waitKey(1)
    frames.pop(0)


cv2.destroyAllWindows()

