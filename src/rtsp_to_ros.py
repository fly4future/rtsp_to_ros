#! /usr/bin/env python3

import os
import sys
import time
import rospy
import cv2
from cv_bridge import CvBridge
from sensor_msgs.msg import Image, CameraInfo
from camera_info_manager import *
from threading import Thread
from time import sleep

verbose = False
camera_frame = ''
camera_info_manager = None
camera_info_publisher = None
is_shutdown = False
async_info_publisher = False
async_info_publisher_freq = 30

def camera_info_publisher_fcn(_):
    global camera_frame, camera_info_manager, camera_info_publisher, async_info_publisher_freq, is_shutdown
    wait_time = 1.0 / async_info_publisher_freq
    while True:
        if is_shutdown or rospy.is_shutdown():
            return
        # publish camera calibration
        camera_info_msg = camera_info_manager.getCameraInfo()
        camera_info_msg.header.frame_id = camera_frame
        camera_info_msg.header.stamp = rospy.Time.now()
        camera_info_publisher.publish(camera_info_msg)
        # wait
        sleep(wait_time)

if __name__ == '__main__':
    # initialize ROS node
    print("Initializing ROS node...")
    rospy.init_node('rtsp_to_ros')
    print("Done!")

    # get ROS parameters
    resource = rospy.get_param('~rtsp_resource')
    camera_name = rospy.get_param('~camera_name')
    camera_frame = rospy.get_param('~camera_frame')
    image_raw_topic = rospy.get_param('~image_raw_topic')
    camera_info_topic = rospy.get_param('~camera_info_topic')

    # open RTSP stream
    rospy.loginfo("Trying to open RTSP resource")
    cap = cv2.VideoCapture(resource)
    if not cap.isOpened():
        rospy.logerr(f"Error opening resource `{resource}`. Please check.")
        sys.exit(0)
    rospy.loginfo("Resource successfully opened")

    # create publishers
    image_pub = rospy.Publisher(image_raw_topic, Image, queue_size=1)
    camera_info_publisher = rospy.Publisher(camera_info_topic, CameraInfo, queue_size=1)

    # initialize ROS_CV_Bridge
    ros_cv_bridge = CvBridge()

    # initialize Camera Info Manager
    camera_info_manager = CameraInfoManager(cname=camera_name, namespace=camera_name)
    camera_info_manager.loadCameraInfo()
    if not camera_info_manager.isCalibrated():
        rospy.logwarn("No calibration found for the current camera")

    # if async_info_publisher, create and launch async publisher node
    if async_info_publisher:
        camera_info_pub = Thread(target=camera_info_publisher_fcn, args=(camera_info_manager,))
        camera_info_pub.start()

    # initialize variables
    print("Correctly opened resource, starting to publish feed.")
    rval, cv_image = cap.read()
    last_t = time.time()
    last_print_t = time.time()
    t_buffer = []

    # process frames
    while rval:
        # get new frame
        rval, cv_image = cap.read()
        # handle Ctrl-C
        key = cv2.waitKey(20)
        if rospy.is_shutdown() or key == 27 or key == 1048603:
            break
        # convert CV image to ROS message
        image_msg = ros_cv_bridge.cv2_to_imgmsg(cv_image, encoding="bgr8")
        image_msg.header.frame_id = camera_frame
        image_msg.header.stamp = rospy.Time.now()
        image_pub.publish(image_msg)
        
        # publish camera calibration in case of sync publisher
        if not async_info_publisher:
            camera_info_msg = camera_info_manager.getCameraInfo()
            camera_info_msg.header.frame_id = camera_frame
            camera_info_msg.header.stamp = image_msg.header.stamp
            camera_info_publisher.publish(camera_info_msg)
        
        # compute frequency
        cur_t = time.time()
        t_buffer.append(cur_t - last_t)
        
        # print frequency (if verbose)
        if cur_t - last_print_t > 1:
            wait_avg_sec = float(sum(t_buffer)) / float(len(t_buffer))
            hz = 1.0 / wait_avg_sec
            if verbose:
                rospy.loginfo(f'Streaming @ {hz:.1f} Hz')
            last_print_t = cur_t
        last_t = cur_t

    # stop thread
    if async_info_publisher:
        is_shutdown = True
        camera_info_pub.join()
