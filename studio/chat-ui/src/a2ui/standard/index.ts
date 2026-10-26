/**
 * Standard A2UI v0.10 component catalog — 18 components.
 */

import type { ComponentCatalog } from "../../types";

import { A2UIAudioPlayer } from "./a2ui-audio-player";
import { A2UIButton } from "./a2ui-button";
import { A2UICard } from "./a2ui-card";
import { A2UICheckBox } from "./a2ui-checkbox";
import { A2UIChoicePicker } from "./a2ui-choice-picker";
import { A2UIColumn } from "./a2ui-column";
import { A2UIDateTimeInput } from "./a2ui-datetime-input";
import { A2UIDivider } from "./a2ui-divider";
import { A2UIIcon } from "./a2ui-icon";
import { A2UIImage } from "./a2ui-image";
import { A2UIList } from "./a2ui-list";
import { A2UIModal } from "./a2ui-modal";
import { A2UIRow } from "./a2ui-row";
import { A2UISlider } from "./a2ui-slider";
import { A2UITabs } from "./a2ui-tabs";
import { A2UIText } from "./a2ui-text";
import { A2UITextField } from "./a2ui-textfield";
import { A2UIVideo } from "./a2ui-video";

export const STANDARD_CATALOG: ComponentCatalog = {
  Text: A2UIText,
  Row: A2UIRow,
  Column: A2UIColumn,
  Card: A2UICard,
  Button: A2UIButton,
  TextField: A2UITextField,
  CheckBox: A2UICheckBox,
  Image: A2UIImage,
  Icon: A2UIIcon,
  Divider: A2UIDivider,
  Tabs: A2UITabs,
  List: A2UIList,
  Modal: A2UIModal,
  Video: A2UIVideo,
  AudioPlayer: A2UIAudioPlayer,
  ChoicePicker: A2UIChoicePicker,
  Slider: A2UISlider,
  DateTimeInput: A2UIDateTimeInput,
};

export {
  A2UIText,
  A2UIRow,
  A2UIColumn,
  A2UICard,
  A2UIButton,
  A2UITextField,
  A2UICheckBox,
  A2UIImage,
  A2UIIcon,
  A2UIDivider,
  A2UITabs,
  A2UIList,
  A2UIModal,
  A2UIVideo,
  A2UIAudioPlayer,
  A2UIChoicePicker,
  A2UISlider,
  A2UIDateTimeInput,
};
