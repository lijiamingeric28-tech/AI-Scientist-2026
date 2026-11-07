import React from 'react'

/**
 * AstroQuery Logo (User Optimized Vector SVG: astroquery-icon(1).svg)
 * Artwork bounds: X: 170-849, Y: 239-711.
 * Focused ViewBox: 160 215 700 515 (~1.359:1 aspect ratio) for zero dead-margin and maximum visual impact.
 */
export default function AstroQueryLogo({
  size = 124,
  width,
  height,
  className = '',
  style = {},
}) {
  const computedW = width || size || 124
  const computedH = height || Math.round((computedW * 515) / 700)

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="160 215 700 515"
      width={computedW}
      height={computedH}
      fill="none"
      className={className}
      style={{
        width: computedW,
        height: computedH,
        display: 'block',
        flexShrink: 0,
        ...style,
      }}
      role="img"
      aria-label="AstroQuery Logo"
    >
      <title id="aq-icon-title">AstroQuery</title>
  <defs>
    <linearGradient id="aq-letter" gradientUnits="userSpaceOnUse"
                    x1="500" y1="350" x2="550" y2="600">
      <stop offset="0" stopColor="#b8cfc2"/>
      <stop offset="0.1577" stopColor="#bad0c4"/>
      <stop offset="0.25" stopColor="#bcd2c6"/>
      <stop offset="0.3462" stopColor="#c1d5ca"/>
      <stop offset="0.4615" stopColor="#c9dbd1"/>
      <stop offset="0.5769" stopColor="#d1e0d7"/>
      <stop offset="0.6731" stopColor="#dae6df"/>
      <stop offset="0.7692" stopColor="#e2ebe6"/>
      <stop offset="0.8654" stopColor="#eaf1ed"/>
      <stop offset="1" stopColor="#f1f5f3"/>
    </linearGradient>
    <linearGradient id="aq-letter-sweep" gradientUnits="userSpaceOnUse" x1="0" y1="554" x2="0" y2="669">
      <stop offset="0" stopColor="#e1eae5"/>
      <stop offset="0.2174" stopColor="#e4ede8"/>
      <stop offset="0.4783" stopColor="#ebf2ee"/>
      <stop offset="0.7565" stopColor="#f2f6f4"/>
      <stop offset="1" stopColor="#f8faf9"/>
    </linearGradient>
    <linearGradient id="aq-letter-foot" gradientUnits="userSpaceOnUse" x1="0" y1="604" x2="0" y2="710">
      <stop offset="0" stopColor="#f2f7f3"/>
      <stop offset="0.283" stopColor="#f5f9f6"/>
      <stop offset="0.5849" stopColor="#f9fbfa"/>
      <stop offset="0.8113" stopColor="#fdfefd"/>
      <stop offset="1" stopColor="#ffffff"/>
    </linearGradient>
    <linearGradient id="aq-orbit-rim" gradientUnits="userSpaceOnUse" x1="186" y1="0" x2="841" y2="0">
      <stop offset="0" stopColor="#fafcfb"/>
      <stop offset="0.0595" stopColor="#f6f9f7"/>
      <stop offset="0.1603" stopColor="#f3f8f5"/>
      <stop offset="0.2656" stopColor="#f4f8f6"/>
      <stop offset="0.3435" stopColor="#f0f6f3"/>
      <stop offset="0.4031" stopColor="#e7f0eb"/>
      <stop offset="0.4794" stopColor="#e0ece5"/>
      <stop offset="0.5557" stopColor="#ddeae3"/>
      <stop offset="0.6702" stopColor="#dbe9e1"/>
      <stop offset="0.7389" stopColor="#ddeae3"/>
      <stop offset="0.8076" stopColor="#e4eee8"/>
      <stop offset="0.8763" stopColor="#ebf3ee"/>
      <stop offset="0.9221" stopColor="#f3f8f5"/>
      <stop offset="0.9603" stopColor="#fafcfb"/>
      <stop offset="1" stopColor="#ffffff"/>
    </linearGradient>
    <linearGradient id="aq-orbit-face" gradientUnits="userSpaceOnUse" x1="186" y1="0" x2="841" y2="0">
      <stop offset="0" stopColor="#fafbfa"/>
      <stop offset="0.0519" stopColor="#f7faf8"/>
      <stop offset="0.0977" stopColor="#f4f7f5"/>
      <stop offset="0.174" stopColor="#f0f5f2"/>
      <stop offset="0.2504" stopColor="#e7efea"/>
      <stop offset="0.2885" stopColor="#dde8e2"/>
      <stop offset="0.3267" stopColor="#d4e2da"/>
      <stop offset="0.3649" stopColor="#cadbd2"/>
      <stop offset="0.4031" stopColor="#c5d8cd"/>
      <stop offset="0.4412" stopColor="#bfd4c8"/>
      <stop offset="0.5099" stopColor="#bbd1c4"/>
      <stop offset="0.6397" stopColor="#b8cfc2"/>
      <stop offset="0.8229" stopColor="#b9cfc3"/>
      <stop offset="0.8855" stopColor="#bcd2c6"/>
      <stop offset="0.9145" stopColor="#c2d6cb"/>
      <stop offset="0.9374" stopColor="#ccdcd3"/>
      <stop offset="0.9603" stopColor="#dce7e1"/>
      <stop offset="0.9802" stopColor="#f2f6f3"/>
      <stop offset="0.9939" stopColor="#fcfdfd"/>
      <stop offset="1" stopColor="#ffffff"/>
    </linearGradient>
    <linearGradient id="aq-orbit-rise" gradientUnits="userSpaceOnUse" x1="246" y1="650" x2="292" y2="584">
      <stop stopColor="#b8cfc1" stopOpacity="0"/>
      <stop offset=".08" stopColor="#b8cfc1" stopOpacity=".1"/>
      <stop offset=".2" stopColor="#b8cfc1" stopOpacity=".33"/>
      <stop offset=".39" stopColor="#b8cfc1" stopOpacity=".6"/>
      <stop offset=".63" stopColor="#b8cfc1" stopOpacity=".85"/>
      <stop offset=".86" stopColor="#b8cfc1" stopOpacity=".98"/>
      <stop offset="1" stopColor="#b8cfc1"/>
    </linearGradient>
    <linearGradient id="aq-orbit-left-bevel" gradientUnits="userSpaceOnUse" x1="229" y1="656" x2="341" y2="550">
      <stop stopColor="#fff" stopOpacity="0"/>
      <stop offset=".33" stopColor="#fff" stopOpacity=".31"/>
      <stop offset=".61" stopColor="#fff" stopOpacity=".24"/>
      <stop offset="1" stopColor="#fff" stopOpacity="0"/>
    </linearGradient>
    <linearGradient id="aq-orbit-right-bevel" gradientUnits="userSpaceOnUse" x1="652" y1="0" x2="780" y2="0">
      <stop stopColor="#fff" stopOpacity="0"/>
      <stop offset=".61" stopColor="#fff" stopOpacity=".12"/>
      <stop offset="1" stopColor="#fff" stopOpacity=".2"/>
    </linearGradient>
    <clipPath id="aq-orbit">
      <path d="M 371 509
               C 270.7 550 187.3 614.7 188 648.5
               C 188.8 680 241 687.3 298 689.6
               C 433.3 695 634.9 626.4 750 555
               C 800.3 523.8 839.9 496.3 834.5 447
               C 827.7 385.2 697.5 402.8 608.5 425.6
               L 608.5 429.2
               C 699.1 416 760 429.4 777.3 457.5
               C 750.6 536.5 473.2 664.9 298 666.6
               C 258.5 666.9 230.6 657.8 230.6 636.1
               C 230.6 616.5 262 594.9 300 566
               C 321 550 345.2 532.5 371 509 Z"/>
    </clipPath>
  </defs>

  

  <g id="aq-monogram">
    <path fill="url(#aq-letter)"
          d="M 505.9 239.1 L 650.2 556.9 L 585.7 585.8 L 508.5 407.2
             H 480.7 V 492.3
             C 446.5 504.2 427.6 534.1 411.8 568.1
             L 339.9 597.5 Z"/>
    <path fill="url(#aq-letter-sweep)"
          d="M 477.8 554.5 C 458.2 602.5 452.3 621.8 365 660.8
             C 347.7 668.5 325.7 671.4 304.4 671.3
             L 326.1 624.9 Z"/>
    <path fill="url(#aq-letter-foot)"
          d="M 602.6 630.3 L 670.5 604.7 L 719.2 711 H 637.8 Z"/>
  </g>

  <path id="aq-star" fill="#b9cfc2"
        d="M 509.4 461.6
           C 515.3 508.2 511.1 516.9 569.4 522.6
           C 511.7 528.2 515.4 537.6 509.4 585.8
           C 503.3 538.1 507.4 528 449.8 522.6
           C 506.1 517.2 503.2 508.8 509.4 461.6 Z"/>

  <g id="aq-orbit-ribbon" clipPath="url(#aq-orbit)">
    <rect x="180" y="398" width="665" height="308" fill="url(#aq-orbit-rim)"/>
    <path fill="url(#aq-orbit-face)"
          d="M 375 498 L 170 597 L 178 646
             C 185 672 234 677.9 294 680
             C 433.1 684.9 635.9 598.2 700 561
             C 760.7 525.8 820.9 486.5 832 442
             L 849 398 L 600 395 L 596 452
             L 746 474 L 583 564 L 366 651 L 253 650 Z"/>
    <path fill="url(#aq-orbit-rise)"
          d="M 380 500 L 179 591 L 176 692 L 251 694
             L 269 650 L 366 548 Z"/>
    <path fill="url(#aq-orbit-left-bevel)"
          d="M 371 509 C 303 547 208 607 210 638
             C 211 653 226 661 260 661
             L 264 630 L 313 566 Z"/>
    <path fill="url(#aq-orbit-right-bevel)"
          d="M 608.5 429.2 C 689 412.5 791 399 777.3 457.5
             C 760 429.4 699.1 416 608.5 429.2 Z"/>
  </g>
    </svg>
  )
}
