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
      <stop offset="0" stopColor="color-mix(in srgb, var(--seed-accent) 45%, var(--seed-bg))"/>
      <stop offset="0.1577" stopColor="color-mix(in srgb, var(--seed-accent) 40%, var(--seed-bg))"/>
      <stop offset="0.25" stopColor="color-mix(in srgb, var(--seed-accent) 35%, var(--seed-bg))"/>
      <stop offset="0.3462" stopColor="color-mix(in srgb, var(--seed-accent) 30%, var(--seed-bg))"/>
      <stop offset="0.4615" stopColor="color-mix(in srgb, var(--seed-accent) 25%, var(--seed-bg))"/>
      <stop offset="0.5769" stopColor="color-mix(in srgb, var(--seed-accent) 20%, var(--seed-bg))"/>
      <stop offset="0.6731" stopColor="color-mix(in srgb, var(--seed-accent) 15%, var(--seed-bg))"/>
      <stop offset="0.7692" stopColor="color-mix(in srgb, var(--seed-accent) 10%, var(--seed-bg))"/>
      <stop offset="0.8654" stopColor="color-mix(in srgb, var(--seed-accent) 6%, var(--seed-bg))"/>
      <stop offset="1" stopColor="var(--seed-bg)"/>
    </linearGradient>
    <linearGradient id="aq-letter-sweep" gradientUnits="userSpaceOnUse" x1="0" y1="554" x2="0" y2="669">
      <stop offset="0" stopColor="color-mix(in srgb, var(--seed-accent) 18%, white)"/>
      <stop offset="0.2174" stopColor="color-mix(in srgb, var(--seed-accent) 14%, white)"/>
      <stop offset="0.4783" stopColor="color-mix(in srgb, var(--seed-accent) 10%, white)"/>
      <stop offset="0.7565" stopColor="color-mix(in srgb, var(--seed-accent) 6%, white)"/>
      <stop offset="1" stopColor="#ffffff"/>
    </linearGradient>
    <linearGradient id="aq-letter-foot" gradientUnits="userSpaceOnUse" x1="0" y1="604" x2="0" y2="710">
      <stop offset="0" stopColor="color-mix(in srgb, var(--seed-accent) 12%, white)"/>
      <stop offset="0.283" stopColor="color-mix(in srgb, var(--seed-accent) 8%, white)"/>
      <stop offset="0.5849" stopColor="color-mix(in srgb, var(--seed-accent) 4%, white)"/>
      <stop offset="0.8113" stopColor="color-mix(in srgb, var(--seed-accent) 2%, white)"/>
      <stop offset="1" stopColor="#ffffff"/>
    </linearGradient>
    <linearGradient id="aq-orbit-rim" gradientUnits="userSpaceOnUse" x1="186" y1="0" x2="841" y2="0">
      <stop offset="0" stopColor="#ffffff"/>
      <stop offset="0.0595" stopColor="color-mix(in srgb, var(--seed-accent) 4%, white)"/>
      <stop offset="0.1603" stopColor="color-mix(in srgb, var(--seed-accent) 8%, white)"/>
      <stop offset="0.2656" stopColor="color-mix(in srgb, var(--seed-accent) 10%, white)"/>
      <stop offset="0.3435" stopColor="color-mix(in srgb, var(--seed-accent) 14%, white)"/>
      <stop offset="0.4031" stopColor="color-mix(in srgb, var(--seed-accent) 18%, white)"/>
      <stop offset="0.4794" stopColor="color-mix(in srgb, var(--seed-accent) 22%, white)"/>
      <stop offset="0.5557" stopColor="color-mix(in srgb, var(--seed-accent) 24%, white)"/>
      <stop offset="0.6702" stopColor="color-mix(in srgb, var(--seed-accent) 24%, white)"/>
      <stop offset="0.7389" stopColor="color-mix(in srgb, var(--seed-accent) 22%, white)"/>
      <stop offset="0.8076" stopColor="color-mix(in srgb, var(--seed-accent) 16%, white)"/>
      <stop offset="0.8763" stopColor="color-mix(in srgb, var(--seed-accent) 10%, white)"/>
      <stop offset="0.9221" stopColor="color-mix(in srgb, var(--seed-accent) 6%, white)"/>
      <stop offset="0.9603" stopColor="color-mix(in srgb, var(--seed-accent) 2%, white)"/>
      <stop offset="1" stopColor="#ffffff"/>
    </linearGradient>
    <linearGradient id="aq-orbit-face" gradientUnits="userSpaceOnUse" x1="186" y1="0" x2="841" y2="0">
      <stop offset="0" stopColor="#ffffff"/>
      <stop offset="0.0519" stopColor="color-mix(in srgb, var(--seed-accent) 5%, white)"/>
      <stop offset="0.0977" stopColor="color-mix(in srgb, var(--seed-accent) 10%, white)"/>
      <stop offset="0.174" stopColor="color-mix(in srgb, var(--seed-accent) 15%, white)"/>
      <stop offset="0.2504" stopColor="color-mix(in srgb, var(--seed-accent) 22%, white)"/>
      <stop offset="0.2885" stopColor="color-mix(in srgb, var(--seed-accent) 28%, white)"/>
      <stop offset="0.3267" stopColor="color-mix(in srgb, var(--seed-accent) 34%, white)"/>
      <stop offset="0.3649" stopColor="color-mix(in srgb, var(--seed-accent) 38%, white)"/>
      <stop offset="0.4031" stopColor="color-mix(in srgb, var(--seed-accent) 42%, white)"/>
      <stop offset="0.4412" stopColor="color-mix(in srgb, var(--seed-accent) 40%, white)"/>
      <stop offset="0.5099" stopColor="color-mix(in srgb, var(--seed-accent) 36%, white)"/>
      <stop offset="0.6397" stopColor="color-mix(in srgb, var(--seed-accent) 34%, white)"/>
      <stop offset="0.8229" stopColor="color-mix(in srgb, var(--seed-accent) 32%, white)"/>
      <stop offset="0.8855" stopColor="color-mix(in srgb, var(--seed-accent) 28%, white)"/>
      <stop offset="0.9145" stopColor="color-mix(in srgb, var(--seed-accent) 22%, white)"/>
      <stop offset="0.9374" stopColor="color-mix(in srgb, var(--seed-accent) 16%, white)"/>
      <stop offset="0.9603" stopColor="color-mix(in srgb, var(--seed-accent) 10%, white)"/>
      <stop offset="0.9802" stopColor="color-mix(in srgb, var(--seed-accent) 5%, white)"/>
      <stop offset="0.9939" stopColor="color-mix(in srgb, var(--seed-accent) 2%, white)"/>
      <stop offset="1" stopColor="#ffffff"/>
    </linearGradient>
    <linearGradient id="aq-orbit-rise" gradientUnits="userSpaceOnUse" x1="246" y1="650" x2="292" y2="584">
      <stop stopColor="color-mix(in srgb, var(--seed-accent) 45%, var(--seed-bg))" stopOpacity="0"/>
      <stop offset=".08" stopColor="color-mix(in srgb, var(--seed-accent) 45%, var(--seed-bg))" stopOpacity=".1"/>
      <stop offset=".2" stopColor="color-mix(in srgb, var(--seed-accent) 45%, var(--seed-bg))" stopOpacity=".33"/>
      <stop offset=".39" stopColor="color-mix(in srgb, var(--seed-accent) 45%, var(--seed-bg))" stopOpacity=".6"/>
      <stop offset=".63" stopColor="color-mix(in srgb, var(--seed-accent) 45%, var(--seed-bg))" stopOpacity=".85"/>
      <stop offset=".86" stopColor="color-mix(in srgb, var(--seed-accent) 45%, var(--seed-bg))" stopOpacity=".98"/>
      <stop offset="1" stopColor="color-mix(in srgb, var(--seed-accent) 45%, var(--seed-bg))"/>
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

  <path id="aq-star" fill="color-mix(in srgb, var(--seed-accent) 45%, var(--seed-bg))"
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
