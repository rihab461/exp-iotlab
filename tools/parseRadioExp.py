#---------------------------------------------------------------------------
# Cedric Adjih
#---------------------------------------------------------------------------

from __future__ import print_function

import argparse
import sys, json, os, pprint
import tarfile, zipfile

import numpy as np
import numpy.ma as ma

import matplotlib.pyplot as plt

#---------------------------------------------------------------------------
# copied from IotlabHelper (and wrote equivalent zillion times)

def readFile(fileName):
    with open(fileName) as f:
        return f.read()

def writeFile(fileName, data):
    with open(fileName, "w") as f:
        f.write(data)

#--------------------------------------------------

J = os.path.join

class FileManager:
    def __init__(self, dirName):
        self.dirName = dirName
        self.zipFile = None

        if os.path.exists(self.dirName+".zip"):
            self.zipFile = zipfile.ZipFile(self.dirName+".zip", "r")
            self.zipNameList = set(self.zipFile.namelist())
        else: self.zipFile = None

        self.tarFile = None
        return # no tar+bzip2|gzip file, slow as molasses (probably decodes
               # everything before, for each extraction)
        suffix = "gz" 
        # suffix = ".bz2"
        if os.path.exists(self.dirName+".tar."+suffix):
            self.tarFile = tarfile.open(self.dirName+".tar."+suffix, 
                                        "r:"+suffix)
            self.tarNameList = set(self.tarFile.getnames())
        else: self.tarFile = None

    def writeFile(self, fileName, data):
        if not os.path.exists(self.dirName):
            os.mkdir(self.dirName)
        writeFile(J(self.dirName, fileName), data)

    def readFile(self, fileName):
        fullPath = J(self.dirName, fileName)
        if not os.path.exists(fullPath):
            if self.zipFile != None:
                f = self.zipFile.open(fullPath)
                result = f.read()
                f.close()
                return result
            elif self.tarFile != None:
                f = self.tarFile.extractfile(fullPath)
                result = f.read()
                f.close()
                return result
        return readFile(fullPath)

    def getPath(self, fileName):
        return J(self.dirName, fileName)

    def exists(self, fileName):
        fullPath = J(self.dirName, fileName)
        return (os.path.exists(fullPath) 
                or (self.zipFile != None and fullPath in self.zipNameList)
                or (self.tarFile != None and fullPath in self.tarNameList))

#---------------------------------------------------------------------------

class ExperimentParser(FileManager):

    def __init__(self, dirName):
        self.dirName = dirName
        FileManager.__init__(self, self.dirName)
        self.generalInfo = eval(self.readFile("meta.pydat"))

    def readNodePos(self):
        resourceList = eval(self.readFile("resources.pydat"))["items"]

        infoOfAddress = {}
        for info in resourceList:
            infoOfAddress[info["network_address"]] = info

        posTable = {}
        for i,nodeInfo in enumerate(self.generalInfo["nodeList"]):
            moreInfo =  infoOfAddress.get(nodeInfo[0])
            posTable[i] = tuple([float(moreInfo[u]) for u in ["x","y","z"]])

        return posTable

    def parseOneBurst(self, fileName, idx):
        info = eval(self.readFile(fileName))
        expInfo = self.generalInfo
        nbNode = len(expInfo["idList"])
        nbPacket = expInfo["nbPacket"]
        
        # check, just in case (normally empty)

        if len(info["unparsed"]) > 0:
            raise ValueError("unparsed information", info["unparsed"])

        # parse sender info

        rawSenderInfo = info["cmdXmit"][1][idx]
        if len(rawSenderInfo) != 2:
            raise ValueError("too much sender info in cmdXmit", rawSenderInfo)
        senderInfo = eval(rawSenderInfo[0][1])
        if senderInfo["nbPacket"] != expInfo["nbPacket"]:
            raise ValueError("inconsistent nb sent packets",
                             (senderInfo["nbPacket"], expInfo["nbPacket"]))
        if senderInfo["nbError"] != 0: # check no error found during exp. 
            raise ValueError("transmission errors found", senderInfo["nbError"])

        edList = []
        for seqNum,(t1,t2,ed,success) in enumerate(senderInfo["send"]):
            if success != 1:
                raise ValueError("transmission failed", 
                                 (senderInfo["send"],seqNum))
            edList.append(ed)

        for otherIdx, eventList in info["cmdXmit"][1].iteritems():
            if otherIdx == idx:
                continue
            if len(eventList) > 0:
                raise ValueError("unexpected output from receiver", 
                                 (otherIdx, eventList))

        xmitId = senderInfo["id"]
        senderPacketList = info["cmdXmit"][1]
        sys.stdout.write(".")
        sys.stdout.flush()

        # check receiver output
        for otherIdx, eventList in info["cmdShow"][1].iteritems():
            if len(eventList) >= 2:
                raise ValueError("multiple output to cmd show",
                                 eventList)
        
        # parse receiver output
        recvTable = {}
        recvTable[idx] = (0,0,[],[],[],[]) # does not receive from itself

        recvArray = np.zeros((nbNode, nbPacket), np.uint8)
        lqiArray = np.zeros((nbNode, nbPacket), np.uint8)
        rssiArray = np.zeros((nbNode, nbPacket), np.uint8)

        notSeenSet = set(range(nbNode))
        for otherIdx, showStr in info["cmdShow"][0].iteritems():
            assert otherIdx in notSeenSet
            notSeenSet.remove(otherIdx)
            if otherIdx == idx:
                continue
            recvInfo = eval(showStr)
            if recvInfo["nbChange"] >= 2:
                print ("\nmultiple changes of xmitId", recvInfo)
            
            countCrcError = 0
            countRecv = 0
            seqNumList = []
            lqiList = []
            rssiList = []
            seqNumPreCrcErrorList = []

            lastSeqNumOk = 0
            for packetInfo in recvInfo["recv"]:
                (i,rssi,lqi,ts,te) = packetInfo
                if packetInfo[0] == 0xffff:
                     countCrcError += 1
                     seqNumPreCrcErrorList.append(lastSeqNumOk)
                     #print (te-ts)
                else: 
                    countRecv += 1
                    lqiList.append(lqi)
                    rssiList.append(rssi)
                    seqNumList.append(i)
                    lastSeqNumOk = 0

                    if not (0 <= i < nbPacket) or recvArray[otherIdx][i]!=0:
                        raise ValueError("invalid packetIdx", i)
                    recvArray[otherIdx][i] = 1
                    lqiArray[otherIdx][i] = lqi
                    rssiArray[otherIdx][i] = rssi

            if recvInfo["id"] != xmitId and countRecv != 0:
                #print (recvInfo["id"], xmitId, countRecv)
                raise ValueError(
                    "bad xmit id", (recvInfo[id], xmitId, recvInfo, countRecv))

            recvTable[otherIdx] = (countRecv,countCrcError,seqNumList,
                                   lqiList, rssiList, seqNumPreCrcErrorList)

        if len(notSeenSet) != 0:
            raise ValueError("missing report", notSeenSet)

        #return edList, recvTable

        del recvTable # not used
        #lqiArray = ma.masked_array(lqiArray, recvArray)
        #rssiArray = ma.masked_array(lqiArray, recvArray)
        return np.array(edList), recvArray, lqiArray, rssiArray

    def parseEveryBurst(self):
        powerList = self.generalInfo["powerList"]
        idxList = self.generalInfo["idList"] # should be [0,1,2,3... n-1]
        channelList = self.generalInfo["channelList"]
        nbNode = len(self.generalInfo["idList"])
        nbPacket = self.generalInfo["nbPacket"]

        dimRecv = (len(powerList), len(channelList), nbNode, nbNode, nbPacket)
        dimSend = (len(powerList), len(channelList), nbNode, nbPacket)
        recvFullArray = np.zeros(dimRecv)
        lqiFullArray = np.zeros(dimRecv)
        rssiFullArray = np.zeros(dimRecv)
        edFullArray = np.zeros(dimSend)
        
        resultTable = {}
        for powerIdx,power in enumerate(powerList):
            for channelIdx,channel in enumerate(channelList):
                for idx in idxList:
                    fileName = ("exp-i%s-p%s-c%s.pydat" % (idx, power, channel))
                    if exp.exists(fileName):
                        (edArray, recvArray, lqiArray, rssiArray 
                         ) = exp.parseOneBurst(fileName, idx)
                        recvFullArray[powerIdx,channelIdx,idx] = recvArray
                        lqiFullArray[powerIdx,channelIdx,idx] = lqiArray
                        rssiFullArray[powerIdx,channelIdx,idx] = rssiArray
                        edFullArray[powerIdx,channelIdx,idx] = edArray
                    else: raise ValueError("missing file", fileName)

        #lqiFullArray = ma.masked_array(lqiFullArray, recvFullArray)
        #rssiFullArray = ma.masked_array(rssiFullArray, recvFullArray)
        return {"recv": recvFullArray, "lqi": lqiFullArray,
                "rssi": rssiFullArray, "ed": edFullArray }

    def parseToMatrix(self):
        summary = self.parseEveryBurst()
        np.savez_compressed(exp.getPath("recv-array"), summary["recv"])
        np.savez_compressed(exp.getPath("rssi-array"), summary["rssi"])
        np.savez_compressed(exp.getPath("lqi-array"), summary["lqi"])
        np.savez_compressed(exp.getPath("ed-array"), summary["ed"])

    def readRecvMatrix(self):
        return numpyReadArray(self.getPath("recv-array.npz"))
    
    def readAllMatrix(self):
        recvArray = numpyReadArray(self.getPath("recv-array.npz"))
        rssiArray = numpyReadArray(self.getPath("rssi-array.npz"))
        lqiArray = numpyReadArray(self.getPath("lqi-array.npz"))
        edArray = numpyReadArray(self.getPath("ed-array.npz"))
        return recvArray, rssiArray, lqiArray, edArray

    def plot(self):
        powerList = self.generalInfo["powerList"]
        idxList = self.generalInfo["idList"] # should be [0,1,2,3... n-1]
        channelList = self.generalInfo["channelList"]
        recvArray =  self.readRecvMatrix()

        print (time.time())
        xList = []
        yList = []
        for powerIdx,power in enumerate(powerList):
            for channelIdx,channel in enumerate(channelList):
                xList.append(channel)
                yList.append(recvArray[powerIdx][channelIdx].sum())
        plt.plot(xList,yList)
        plt.ylim(0)

        print (time.time())


        #for power in powerList:
        #    for :

#---------------------------------------------------------------------------

# XXX:remove
#PowerList = [
#    "-17", "-12", "-9", "-7", "-5", "-4", "-3", "-2", "-1",
#    "0", "0.7", "1.3", "1.8", "2.3", "2.8", "3"]
#powerList = PowerList



parser = argparse.ArgumentParser()
subparsers = parser.add_subparsers(dest="command")

rawParserParser = subparsers.add_parser("parse")
rawParserParser.add_argument("dirName", type=str)

summaryParser = subparsers.add_parser("summary")
summaryParser.add_argument("dirName", type=str)

args = parser.parse_args()

def numpyReadArray(fileName):
    npzFile = np.load(fileName)
    keyList = npzFile.keys()
    if len(keyList) >= 2:
        raise ValueError("More than 2 keys", keyList)
    return npzFile[keyList[0]]


if args.command == "parse":
    exp = ExperimentParser(args.dirName)
    exp.parseToMatrix()

elif args.command == "summary":
    exp = ExperimentParser(args.dirName)
    exp.plot()
    #np.savez_compressed(exp.getPath("rssi-array"), summary["lqi"])
    #np.savez_compressed(exp.getPath("lqi-array"), summary["rssi"])
    #np.savez_compressed(exp.getPath("ed-array"), summary["ed"])

#    summary = eval(exp.readFile("summary.pydat"))


#---------------------------------------------------------------------------
