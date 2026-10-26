# sam-segmentation-mcp

Local Ultralytics SAM 3 concept segmentation tools for object-specific image
counting. The count is an estimated open-vocabulary concept instance count.

## Triggers

- The user wants to count objects matching a text concept in an image.
- The user asks how many dogs, people, red apples, school buses, or similar
  concept instances appear in an image.
- The user wants SAM 3 concept segmentation through OpenBench.

## Tools

- `count_objects_with_sam3` - use SAM 3 to segment and count instances matching
  one required text concept.
- `service_info` - inspect SAM 3 weight status and service limits.

## Dependencies

- mcp[cli]
- ultralytics>=8.3.237
- torch
- Pillow
- numpy

## Version

0.2.0
