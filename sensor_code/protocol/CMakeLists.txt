#-._.-=-._.-=-._.-=-._.-=-._.-=-._.-=-._.-=-._.-=-._.-=-._.-=-._.-                                            
# ProtoBuffer (nanopb) generation
#-._.-=-._.-=-._.-=-._.-=-._.-=-._.-=-._.-=-._.-=-._.-=-._.-=-._.-
# Generate C sources from phase1.proto using nanopb generator when source .proto or .options change.
set(PHASE1_PROTO_DIR ${CMAKE_CURRENT_SOURCE_DIR})
set(PHASE1_PROTO ${PHASE1_PROTO_DIR}/app.proto
                 ${PHASE1_PROTO_DIR}/Common.proto
                 ${PHASE1_PROTO_DIR}/command.proto
                 ${PHASE1_PROTO_DIR}/configuration.proto
                 ${PHASE1_PROTO_DIR}/fota.proto
                 ${PHASE1_PROTO_DIR}/measurement.proto
                 ${PHASE1_PROTO_DIR}/session.proto)
set(PHASE1_OPTIONS ${PHASE1_PROTO_DIR}/phase1.options)

# Expected generated files (nanopb naming convention: <name>.pb.c / <name>.pb.h)
set(PHASE1_GEN_C ${PHASE1_PROTO_DIR}/app.pb.c
                 ${PHASE1_PROTO_DIR}/Common.pb.c
                 ${PHASE1_PROTO_DIR}/command.pb.c
                 ${PHASE1_PROTO_DIR}/configuration.pb.c
                 ${PHASE1_PROTO_DIR}/fota.pb.c
                 ${PHASE1_PROTO_DIR}/measurement.pb.c
                 ${PHASE1_PROTO_DIR}/session.pb.c)
set(PHASE1_GEN_H ${PHASE1_PROTO_DIR}/app.pb.h
                 ${PHASE1_PROTO_DIR}/Common.pb.h
                 ${PHASE1_PROTO_DIR}/command.pb.h
                 ${PHASE1_PROTO_DIR}/configuration.pb.h
                 ${PHASE1_PROTO_DIR}/fota.pb.h
                 ${PHASE1_PROTO_DIR}/measurement.pb.h
                 ${PHASE1_PROTO_DIR}/session.pb.h)
