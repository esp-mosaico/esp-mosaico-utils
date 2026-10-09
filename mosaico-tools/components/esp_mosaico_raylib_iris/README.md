# Raylib native Iris application services

Vibe's Iris build wrapper requires this component. Engine Boards contain no Iris
code. The shared native launcher explicitly links the selected provider; failure
to provide it is a link error, rather than falling back to an empty startup hook.

The provider starts Iris before Board initialization, borrows video/input
interfaces after Board creation, confirms health after the accepted and flushed
first frame and input startup, and unregisters before Board destruction. An
unregister failure retains the Board so callbacks cannot access freed resources.
USB transport and Recovery-first updates are required; automatic health acceptance
is rejected. A fresh build directory is needed when migrating an older sdkconfig
that enabled automatic acceptance.

The screenshot/pointer adapter is owned here. It uses the Engine's neutral video
and input contracts, with no concrete BSP dependency. Retained factory Recovery
remains a separately provisioned firmware.
