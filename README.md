# Vehicle Telemetry Platform

An embedded edge based platform for telemetry based vehicle analysis. 

### **Important:** This project uses a custom library handling ESP32 OBD-II over CAN with support for multiframe using ISO 15765-2. This library can be found at https://github.com/BuvinduS/OBD2Lib.git

## Proposed Project Timeline (subject to change)

![Timeline](images/timeline_gantt.png)


## Current Progress

### Phase 1 (On Going)
- OBD2-II library implementation (logic based) complete.
- Concerte implementation of MCP2515 over SPI implemented. This included serveral notable (sub) phases:
    - **Phase 1** : Established proper communication over **RAW SPI** to the MCP2515, verified wirings and crystal frequency, encountered an issue in using GPIO 11 and 10 of the ESP32-S3-devkitc-1. However pins 4 and 5 worked therefore implementation shifted to those pins. Cause of failure of pin 11 and 10 were not investigated in detail.
    - **Phase 2**: Successfully completed loopback testing in in the MCP2515. Sent test frame and recieved frame were identical, confirming proper communication. Used `autowp/arduino-mcp2515` for ease. Can be found at https://github.com/autowp/arduino-mcp2515.git
    - **Phase 3**: Concrete implementaion that matches `OBDTrasport` of OBD2lib. Thin wrapper around `autowp/autowp-mcp2515` 
    Note: **Real testing with an actual vehicle is yet to be confirmed, hence this section is still open.**
- Data consumption/processing started (this repository). Uses jupyter note books and available mock data from the feasibility test to build the pipeline. Once functionality is verified will be used with actual data from a vehicle to analyse the data ot find trends, correlations etc.