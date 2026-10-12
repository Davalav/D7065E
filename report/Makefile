# Build the D2 diagrams and the LaTeX architecture document.
#
# Requires:
#   * d2      -- `go install oss.terrastruct.com/d2@latest`
#   * Chrome, Edge or Chromium (svg2pdf.py prints D2's SVG to vector PDF;
#     D2's own PNG export needs a Playwright download that no longer exists)
#   * TeX Live with pdflatex + pgfplots (or the Docker command in README.md)
#
# Usage:
#   make            # render changed diagrams and build final_report.pdf
#   make diagrams   # only (re)render the diagrams
#   make clean      # remove LaTeX intermediates
#   make distclean  # also remove the PDF and rendered figures

D2       ?= d2
PYTHON   ?= python
D2FLAGS  := --theme 4 --pad 25
PDFLATEX := pdflatex -interaction=nonstopmode -halt-on-error
DOC      := final_report

# The context diagram lays out better with dagre; everything else with elk.
DAGRE := context
ELK   := container component dynamic state deployment pipeline simloop
FIGS  := $(DAGRE:%=figures/%.pdf) $(ELK:%=figures/%.pdf)

.PHONY: all diagrams clean distclean
all: $(DOC).pdf

diagrams: $(FIGS)

$(DAGRE:%=build/svg/%.svg): build/svg/%.svg: diagrams/%.d2
	@mkdir -p build/svg
	$(D2) $(D2FLAGS) --layout dagre $< $@

$(ELK:%=build/svg/%.svg): build/svg/%.svg: diagrams/%.d2
	@mkdir -p build/svg
	$(D2) $(D2FLAGS) --layout elk $< $@

figures/%.pdf: build/svg/%.svg svg2pdf.py
	$(PYTHON) svg2pdf.py $<

$(DOC).pdf: $(DOC).tex $(FIGS) $(wildcard data/*.csv) $(wildcard figures/*.png)
	$(PDFLATEX) $(DOC).tex
	$(PDFLATEX) $(DOC).tex

clean:
	rm -f $(DOC).aux $(DOC).log $(DOC).out $(DOC).toc

distclean: clean
	rm -rf $(DOC).pdf build $(FIGS)
