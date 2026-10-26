# vehicle-plate-reading

Read vehicle license plates from images using a vision-language model, then
return the most likely plate text with uncertainty notes instead of guessing.
Use this skill as a domain prompt layer on top of a general VLM provider or
VisionAgent; it does not replace the underlying vision model.

## Triggers

- User asks to read a vehicle plate, number plate, license plate, nomor polisi,
  nopol, plat nomor, or registration number from an image
- User uploads traffic, parking, toll, security, or vehicle inspection imagery
  and asks for identification details
- Agent needs a structured visual answer that separates the plate text,
  confidence, vehicle context, and uncertainty

## Reading Protocol

1. Inspect only visible text in the image. Do not infer missing characters from
   vehicle brand, region, or prior context unless the user explicitly asks.
2. Preserve the original plate casing and spacing when visible.
3. If characters are ambiguous, use `?` for the uncertain character and explain
   the ambiguity.
4. Return a compact result with these fields:
   - `plate_text`: best visible reading
   - `confidence`: high, medium, or low
   - `evidence`: short description of where/how the plate appears
   - `uncertainty`: blur, angle, glare, occlusion, low resolution, or none
5. If no readable plate is visible, say that no readable plate is visible.

## Version

0.1.0
