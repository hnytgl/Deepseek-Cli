class DeepseekCodexCli < Formula
  include Language::Python::Virtualenv

  desc "Codex-style command line coding agent powered by DeepSeek"
  homepage "https://github.com/hnytgl/deepseek-cli"
  url "https://github.com/hnytgl/deepseek-cli/archive/refs/tags/v0.5.0.tar.gz"
  sha256 "REPLACE_WITH_RELEASE_TARBALL_SHA256"
  license "MIT"

  depends_on "python@3.12"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "deepseek-codex-cli", shell_output("#{bin}/deepseek --version")
  end
end
