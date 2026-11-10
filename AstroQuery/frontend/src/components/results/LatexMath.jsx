import React, { useMemo } from 'react';
import katex from 'katex';
import 'katex/dist/katex.min.css';

/**
 * Renders a LaTeX mathematical formula or block equation.
 * If displayMode is true, renders as a standalone block formula.
 */
export function LatexMath({ math, formula, displayMode = false, className = '' }) {
  const rawInput = math || formula;
  if (!rawInput || typeof rawInput !== 'string') {
    return null;
  }

  const renderedHtml = useMemo(() => {
    let cleaned = rawInput.trim();
    if (!cleaned) return '';

    // Strip enclosing $$, $, or \[ \]
    if (cleaned.startsWith('$$') && cleaned.endsWith('$$')) {
      cleaned = cleaned.slice(2, -2).trim();
    } else if (cleaned.startsWith('$') && cleaned.endsWith('$') && cleaned.length > 2) {
      cleaned = cleaned.slice(1, -1).trim();
    } else if (cleaned.startsWith('\\[') && cleaned.endsWith('\\]')) {
      cleaned = cleaned.slice(2, -2).trim();
    }

    try {
      return katex.renderToString(cleaned, {
        displayMode: displayMode,
        throwOnError: false,
        output: 'htmlAndMathml',
      });
    } catch (err) {
      console.warn('KaTeX render error:', err);
      return `<code class="katex-fallback">${cleaned}</code>`;
    }
  }, [rawInput, displayMode]);

  return (
    <div
      className={`latex-math-container ${displayMode ? 'is-display' : 'is-inline'} ${className}`}
      dangerouslySetInnerHTML={{ __html: renderedHtml }}
    />
  );
}

/**
 * Renders prose text that may contain inline math denoted by $...$
 */
export function LatexText({ text, className = '' }) {
  if (!text || typeof text !== 'string') {
    return null;
  }

  const renderedHtml = useMemo(() => {
    const raw = text.trim();
    if (!raw) return '';

    // If string has raw LaTeX commands without $, render the whole expression
    if (!raw.includes('$') && /(\\[a-zA-Z]+|\^|\_)/.test(raw)) {
      try {
        return katex.renderToString(raw, {
          displayMode: false,
          throwOnError: false,
          output: 'htmlAndMathml',
        });
      } catch (err) {
        // Fall back
      }
    }

    // Check if contains $...$
    if (!raw.includes('$')) {
      return null; // Let React render plain text directly
    }

    try {
      const parts = raw.split(/(\$[^$]+\$)/g);
      return parts.map(part => {
        if (part.startsWith('$') && part.endsWith('$') && part.length > 2) {
          const formula = part.slice(1, -1);
          return katex.renderToString(formula, {
            displayMode: false,
            throwOnError: false,
            output: 'htmlAndMathml',
          });
        }
        return part
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;');
      }).join('');
    } catch (err) {
      console.warn('KaTeX inline render error:', err);
      return null;
    }
  }, [text]);

  if (!renderedHtml) {
    return <span className={className}>{text}</span>;
  }

  return (
    <span
      className={`latex-prose-text ${className}`}
      dangerouslySetInnerHTML={{ __html: renderedHtml }}
    />
  );
}

export default LatexMath;
