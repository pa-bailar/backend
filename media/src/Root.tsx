// Every video's compositions, one folder each in the Studio. A new video: add its folder under projects/ and one
// line here.
import React from "react";
import "./lib/fonts";
import { EsteFindeVideo } from "../projects/este-finde/EsteFinde";
import { TeaserV2 } from "../projects/teaser-v2/Teaser";
import { PuenteVideo } from "../projects/puente/Puente";

export const RemotionRoot: React.FC = () => (
  <>
    <TeaserV2 />
    <EsteFindeVideo />
    <PuenteVideo />
  </>
);
