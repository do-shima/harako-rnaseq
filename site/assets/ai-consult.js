(() => {
  "use strict";

  const PROVIDERS = Object.freeze({
    ChatGPT: "https://chatgpt.com/",
    Gemini: "https://gemini.google.com/",
    Claude: "https://claude.ai/",
    Perplexity: "https://www.perplexity.ai/",
  });

  const COPY = Object.freeze({
    en: {
      launcher: "Ask an AI",
      dialogTitle: "Ask an AI about Harako-RNAseq",
      introduction:
        "Create a reviewable prompt, copy it locally, and open an AI service without sending the prompt automatically.",
      topicLabel: "Consultation topic",
      topics: [
        "Check whether my environment can run Harako",
        "Discuss whether Harako fits my experimental design",
        "Discuss analysis of SRR/ENA data",
        "Draft a Methods description",
        "Organize likely causes of an error",
        "Other",
      ],
      questionLabel: "Question (optional)",
      questionPlaceholder: "Add only information that is safe to copy and share.",
      promptLabel: "Generated prompt (review before sharing)",
      providersLabel: "Copy the prompt and open a provider",
      copyOnly: "Copy prompt only",
      close: "Close",
      privacy:
        "Harako does not send the prompt, question, page text, page URL, or user input to an AI provider. The prompt is copied locally; you must review, paste, and submit it yourself. The provider's own privacy terms apply after you submit content there. Do not include FASTQ data, patient information, credentials, unpublished sample identifiers, or private absolute paths.",
      ready: "The prompt is ready for review.",
      copied: "Prompt copied. Review it before pasting or submitting it.",
      opened: (provider) =>
        `Prompt copied and ${provider} opened in a new tab. Review, paste, and submit it yourself.`,
      copyFailed: (provider) =>
        `Automatic copying was unavailable. The prompt is selected for manual copying; ${provider} opened without receiving it.`,
      popupBlocked:
        "Prompt copied, but the provider tab was blocked. Allow pop-ups or use the provider homepage manually.",
      copyOnlyFailed:
        "Automatic copying was unavailable. The prompt is selected below so you can copy it manually.",
      prompt: {
        request: "Please help me with Harako-RNAseq using the context below.",
        title: "Public page title",
        url: "Official public page URL",
        description: "Page description",
        topic: "Consultation topic",
        question: "My question",
        noQuestion: "No additional question provided.",
        harako: "About Harako-RNAseq",
        harakoDescription:
          "Harako-RNAseq is a local, Docker-based graphical bulk RNA-seq workflow from FASTQ through fastp, Salmon, tximport, DESeq2 or QC-only analysis, and a self-contained HTML report.",
        safety: "Safety and answer requirements",
        instructions: [
          "Prioritize official Harako documentation for Harako-specific behavior.",
          "Do not infer biological conditions, controls, or biological independence; identify them as facts the user must explicitly confirm.",
          "Do not request FASTQ data or confidential data.",
          "Present unknown or uncertain facts as confirmation items rather than assumptions.",
          "Keep the Harako citation distinct from citations for underlying tools such as fastp, Salmon, tximport, and DESeq2.",
        ],
      },
    },
    ja: {
      launcher: "AIに相談",
      dialogTitle: "Harako-RNAseqについてAIに相談",
      introduction:
        "確認可能なプロンプトを端末内でコピーし、内容を自動送信せずにAIサービスを開きます。",
      topicLabel: "相談内容",
      topics: [
        "導入できる環境か確認したい",
        "実験計画への適用を相談したい",
        "SRR/ENAデータの解析を相談したい",
        "論文Methodsの記載を作りたい",
        "エラーの原因を整理したい",
        "その他",
      ],
      questionLabel: "質問（任意）",
      questionPlaceholder: "コピーして共有しても安全な情報だけを入力してください。",
      promptLabel: "生成されたプロンプト（共有前に確認）",
      providersLabel: "プロンプトをコピーしてAIサービスを開く",
      copyOnly: "プロンプトのみコピー",
      close: "閉じる",
      privacy:
        "HarakoからAIサービスへ、プロンプト、質問、ページ本文、ページURL、入力内容を送信することはありません。プロンプトは端末内でコピーされるだけで、内容の確認、貼り付け、送信は利用者自身が行います。送信後は各サービスのプライバシー条件が適用されます。FASTQデータ、患者情報、認証情報、未公開のサンプル識別子、非公開の絶対パスを含めないでください。",
      ready: "プロンプトを確認できます。",
      copied: "プロンプトをコピーしました。貼り付けや送信の前に内容を確認してください。",
      opened: (provider) =>
        `プロンプトをコピーし、${provider}を新しいタブで開きました。内容を確認してから、ご自身で貼り付けて送信してください。`,
      copyFailed: (provider) =>
        `自動コピーを利用できませんでした。手動コピーできるようプロンプトを選択しました。${provider}には情報を渡さずにページのみ開きました。`,
      popupBlocked:
        "プロンプトはコピーしましたが、AIサービスのタブがブロックされました。ポップアップを許可するか、サービスのホームページを直接開いてください。",
      copyOnlyFailed:
        "自動コピーを利用できませんでした。下のプロンプトを選択したので、手動でコピーしてください。",
      prompt: {
        request: "以下の情報に基づいて、Harako-RNAseqについて支援してください。",
        title: "公開ページのタイトル",
        url: "公式公開ページURL",
        description: "ページの説明",
        topic: "相談内容",
        question: "質問",
        noQuestion: "追加の質問はありません。",
        harako: "Harako-RNAseqについて",
        harakoDescription:
          "Harako-RNAseqは、FASTQからfastp、Salmon、tximport、DESeq2またはQC-only解析、自己完結型HTMLレポートまでを扱う、ローカルで動作するDockerベースのGUIバルクRNA-seqワークフローです。",
        safety: "安全性と回答に関する要件",
        instructions: [
          "Harako固有の動作については、Harakoの公式ドキュメントを優先してください。",
          "生物学的条件、対照群、生物学的独立性を推測せず、利用者が明示的に確認すべき事項として示してください。",
          "FASTQデータや機密情報の提供を求めないでください。",
          "不明または不確かな事実は、仮定せず確認事項として示してください。",
          "Harakoの引用と、fastp、Salmon、tximport、DESeq2など基盤ツールの引用を区別してください。",
        ],
      },
    },
  });

  function makeElement(tag, options = {}) {
    const element = document.createElement(tag);
    if (options.className) element.className = options.className;
    if (options.text) element.textContent = options.text;
    if (options.attributes) {
      Object.entries(options.attributes).forEach(([name, value]) => {
        element.setAttribute(name, value);
      });
    }
    return element;
  }

  function pageMetadata() {
    const description = document.querySelector('meta[name="description"]');
    const canonical = document.querySelector('link[rel="canonical"]');
    return {
      title: document.title.trim(),
      url: canonical ? canonical.href : "",
      description: description ? description.content.trim() : "",
    };
  }

  function buildPrompt(copy, topic, question) {
    const metadata = pageMetadata();
    const prompt = copy.prompt;
    const lines = [
      prompt.request,
      "",
      `${prompt.title}: ${metadata.title}`,
      `${prompt.url}: ${metadata.url}`,
      `${prompt.description}: ${metadata.description}`,
      `${prompt.topic}: ${topic}`,
      `${prompt.question}: ${question || prompt.noQuestion}`,
      "",
      `${prompt.harako}:`,
      prompt.harakoDescription,
      "",
      `${prompt.safety}:`,
      ...prompt.instructions.map((instruction) => `- ${instruction}`),
    ];
    return lines.join("\n");
  }

  function fallbackCopy(output) {
    output.focus();
    output.select();
    output.setSelectionRange(0, output.value.length);
    try {
      return document.execCommand("copy");
    } catch (_error) {
      return false;
    }
  }

  async function copyPrompt(text, output) {
    output.value = text;
    if (navigator.clipboard && window.isSecureContext) {
      try {
        await navigator.clipboard.writeText(text);
        return true;
      } catch (_error) {
        // Continue with the local selection-based fallback.
      }
    }
    return fallbackCopy(output);
  }

  function initialize() {
    const language = document.documentElement.lang.toLowerCase().startsWith("ja")
      ? "ja"
      : "en";
    const copy = COPY[language];

    const launcher = makeElement("button", {
      className: "ai-consult-launcher",
      text: copy.launcher,
      attributes: {
        type: "button",
        "aria-haspopup": "dialog",
        "aria-controls": "ai-consult-dialog",
        "aria-expanded": "false",
      },
    });

    const dialog = makeElement("dialog", {
      className: "ai-consult-dialog",
      attributes: {
        id: "ai-consult-dialog",
        role: "dialog",
        "aria-modal": "true",
        "aria-labelledby": "ai-consult-title",
      },
    });
    const panel = makeElement("div", { className: "ai-consult-panel" });
    const header = makeElement("div", { className: "ai-consult-header" });
    const title = makeElement("h2", {
      text: copy.dialogTitle,
      attributes: { id: "ai-consult-title" },
    });
    const closeButton = makeElement("button", {
      className: "ai-consult-close",
      text: "×",
      attributes: { type: "button", "aria-label": copy.close },
    });
    header.append(title, closeButton);

    const introduction = makeElement("p", {
      className: "ai-consult-introduction",
      text: copy.introduction,
    });

    const topicField = makeElement("div", { className: "ai-consult-field" });
    const topicLabel = makeElement("label", {
      text: copy.topicLabel,
      attributes: { for: "ai-consult-topic" },
    });
    const topicSelect = makeElement("select", {
      attributes: { id: "ai-consult-topic" },
    });
    copy.topics.forEach((topic) => {
      topicSelect.append(makeElement("option", { text: topic, attributes: { value: topic } }));
    });
    topicField.append(topicLabel, topicSelect);

    const questionField = makeElement("div", { className: "ai-consult-field" });
    const questionLabel = makeElement("label", {
      text: copy.questionLabel,
      attributes: { for: "ai-consult-question" },
    });
    const question = makeElement("textarea", {
      attributes: {
        id: "ai-consult-question",
        rows: "3",
        placeholder: copy.questionPlaceholder,
      },
    });
    questionField.append(questionLabel, question);

    const promptField = makeElement("div", { className: "ai-consult-field" });
    const promptLabel = makeElement("label", {
      text: copy.promptLabel,
      attributes: { for: "ai-consult-prompt" },
    });
    const promptOutput = makeElement("textarea", {
      className: "ai-consult-prompt",
      attributes: { id: "ai-consult-prompt", rows: "9", readonly: "" },
    });
    promptField.append(promptLabel, promptOutput);

    const privacy = makeElement("p", {
      className: "ai-consult-privacy",
      text: copy.privacy,
    });
    const providersLabel = makeElement("p", {
      className: "ai-consult-providers-label",
      text: copy.providersLabel,
      attributes: { id: "ai-consult-providers-label" },
    });
    const providerGrid = makeElement("div", {
      className: "ai-consult-provider-grid",
      attributes: { "aria-labelledby": "ai-consult-providers-label" },
    });
    const copyOnly = makeElement("button", {
      className: "ai-consult-copy-only",
      text: copy.copyOnly,
      attributes: { type: "button" },
    });
    const status = makeElement("p", {
      className: "ai-consult-status",
      text: copy.ready,
      attributes: { role: "status", "aria-live": "polite", "aria-atomic": "true" },
    });

    function renderPrompt() {
      promptOutput.value = buildPrompt(copy, topicSelect.value, question.value.trim());
      return promptOutput.value;
    }

    function closeDialog() {
      if (typeof dialog.close === "function" && dialog.open) {
        dialog.close();
      } else {
        dialog.removeAttribute("open");
        launcher.setAttribute("aria-expanded", "false");
        launcher.focus();
      }
    }

    async function openProvider(name) {
      const copyOperation = copyPrompt(renderPrompt(), promptOutput);
      const providerTab = window.open(
        PROVIDERS[name],
        "_blank",
        "noopener,noreferrer",
      );
      const copied = await copyOperation;

      if (!providerTab) {
        status.textContent = copied ? copy.popupBlocked : copy.copyOnlyFailed;
        return;
      }

      status.textContent = copied ? copy.opened(name) : copy.copyFailed(name);
    }

    Object.keys(PROVIDERS).forEach((name) => {
      const providerButton = makeElement("button", {
        text: name,
        attributes: { type: "button" },
      });
      providerButton.addEventListener("click", () => openProvider(name));
      providerGrid.append(providerButton);
    });

    topicSelect.addEventListener("change", renderPrompt);
    question.addEventListener("input", renderPrompt);
    copyOnly.addEventListener("click", async () => {
      const copied = await copyPrompt(renderPrompt(), promptOutput);
      status.textContent = copied ? copy.copied : copy.copyOnlyFailed;
    });
    launcher.addEventListener("click", () => {
      renderPrompt();
      launcher.setAttribute("aria-expanded", "true");
      if (typeof dialog.showModal === "function") {
        dialog.showModal();
      } else {
        dialog.setAttribute("open", "");
      }
      topicSelect.focus();
    });
    closeButton.addEventListener("click", closeDialog);
    dialog.addEventListener("close", () => {
      launcher.setAttribute("aria-expanded", "false");
      launcher.focus();
    });
    dialog.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && dialog.hasAttribute("open")) {
        event.preventDefault();
        closeDialog();
      }
    });
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) closeDialog();
    });

    renderPrompt();
    panel.append(
      header,
      introduction,
      topicField,
      questionField,
      promptField,
      privacy,
      providersLabel,
      providerGrid,
      copyOnly,
      status,
    );
    dialog.append(panel);
    document.body.append(launcher, dialog);
  }

  initialize();
})();
