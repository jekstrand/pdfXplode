# Copyright © 2020 Jason Ekstrand
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

from fbs_runtime.application_context.PyQt5 import ApplicationContext
from inputPDF import InputPDFFile, InputPDFPage
from inputImage import InputImage
import math
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtPrintSupport import *
from PyQt5.QtWidgets import *
import os
from outputPDF import ThreadedOperation, printInputImage
import sys
import tempfile
from units import *

MILE_IN_POINTS = 72 * 12 * 5280

class UnitsComboBox(QComboBox):
    valueChanged = pyqtSignal(str)

    def __init__(self, parent=None):
        super(UnitsComboBox, self).__init__(parent)
        self.setEditable(False)
        self.currentTextChanged.connect(self._parentTextChanged)
        self._updating = False

    def _parentTextChanged(self, text):
        if not self._updating:
            self.valueChanged.emit(text)

    def value(self):
        return self.currentText()

    def setAvailableUnits(self, availableUnits):
        self._updating = True
        old = self.currentText()
        self.clear()
        self.addItems(availableUnits)
        self._updating = False
        self.setCurrentText(old)

class ScaledSpinBox(QWidget):
    valueChanged = pyqtSignal(float)

    def __init__(self, parent=None):
        super(ScaledSpinBox, self).__init__(parent)

        self._raw = QDoubleSpinBox()
        self._raw.valueChanged.connect(self._rawValueChanged)
        self._updating = False
        self._scale = 1

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._raw)
        self.setLayout(layout)

    def _rawValueChanged(self, rawValue):
        if not self._updating:
            self.valueChanged.emit(rawValue * self._scale)

    def minimum(self):
        return self._raw.minimum() * self._scale

    def setMinimum(self, value):
        self._raw.setMinimum(value / self._scale)

    def maximum(self):
        return self._raw.maximum() * self._scale

    def setMaximum(self, value):
        self._raw.setMaximum(value / self._scale)

    def value(self):
        return self._raw.value() * self._scale

    def setValue(self, value):
        self._raw.setValue(value / self._scale)

    def singleStep(self):
        return self._raw.singleStep() * self._scale

    def setSingleStep(self, step):
        self._raw.setSingleStep(step / self._scale)

    def scale(self):
        return self._scale

    def setScale(self, scale):
        mini = self.minimum()
        maxi = self.maximum()
        step = self.singleStep()
        value = self.value()
        self.updating = True
        self._scale = scale
        self.setMinimum(mini)
        self.setMaximum(maxi)
        self.setSingleStep(step)
        self.setValue(value)
        self.updating = False

class DimWidget(QWidget):
    valueChanged = pyqtSignal(float, float)

    def __init__(self, ctx, xName='X', yName='Y', compact=False, parent=None):
        super(DimWidget, self).__init__(parent)

        self._updating = False

        self.displayUnit = POINTS
        self.baseUnit = POINTS
        self.xBase = 1
        self.yBase = 1

        self.xSpin = ScaledSpinBox()
        self.xSpin.valueChanged.connect(self._xChanged)
        self.ySpin = ScaledSpinBox()
        self.ySpin.valueChanged.connect(self._yChanged)
        self.link = None

        if compact:
            layout = QHBoxLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(self.xSpin)
            layout.addWidget(QLabel('x'))
            layout.addWidget(self.ySpin)
            self.setLayout(layout)
        else:
            self.linkIcon = QIcon(ctx.get_resource('icons/spin-link.svg'))
            self.unlinkIcon = QIcon(ctx.get_resource('icons/spin-unlink.svg'))
            self.link = QPushButton()
            self.link.setIcon(self.linkIcon)
            self.link.setCheckable(True)
            self.link.setChecked(True)
            self.link.setFixedSize(32, 40)
            self.link.toggled.connect(self._linkToggled)

            layout = QGridLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(QLabel(xName + ':'), 0, 0, 2, 1)
            layout.addWidget(self.xSpin, 0, 1, 2, 1)
            layout.addWidget(QLabel(yName + ':'), 2, 0, 2, 1)
            layout.addWidget(self.ySpin, 2, 1, 2, 1)
            layout.addWidget(QLabel('↰'), 0, 2, 1, 1)
            layout.addWidget(self.link, 1, 2, 2, 1)
            layout.addWidget(QLabel('↲'), 3, 2, 1, 1)
            self.setLayout(layout)

    def _xChanged(self, x):
        if self._updating:
            return

        if self.linked():
            self._updating = True
            self.ySpin.setValue(x * (self.yBase / self.xBase))
            self._updating = False

        self.valueChanged.emit(x, self.ySpin.value())

    def _yChanged(self, y):
        if self._updating:
            return

        if self.linked():
            self._updating = True
            self.xSpin.setValue(y * (self.xBase / self.yBase))
            self._updating = False

        self.valueChanged.emit(self.xSpin.value(), y)

    def _linkToggled(self, checked):
        if checked:
            self.link.setIcon(self.linkIcon)
        else:
            self.link.setIcon(self.unlinkIcon)

    def values(self):
        return self.xSpin.value(), self.ySpin.value()

    def setValues(self, x, y):
        if x != self.xSpin.value() or y != self.ySpin.value():
            self._updating = True
            self.xSpin.setValue(x)
            self.ySpin.setValue(y)
            self._updating = False
            self.valueChanged.emit(x, y)

    def setMaximums(self, xMax, yMax):
        self.xSpin.setMaximum(xMax)
        self.ySpin.setMaximum(yMax)

    def _resetScale(self):
        if self.displayUnit == PERCENT:
            self.xSpin.setScale(self.xBase / 100)
            self.ySpin.setScale(self.yBase / 100)
        else:
            scale = getConversionFactor(self.displayUnit, self.baseUnit)
            self.xSpin.setScale(scale)
            self.ySpin.setScale(scale)

    def setBaseValues(self, xBase, yBase):
        if xBase == 0 or yBase == 0:
            return

        if xBase == self.xBase and yBase == self.yBase:
            return

        x = self.xSpin.value()
        y = self.ySpin.value()

        if self.linked() and x and y and xBase and yBase:
            if xBase == self.xBase:
                y = x * yBase / xBase
            elif yBase == self.yBase:
                x = y * xBase / yBase
            elif abs((x / y) - (xBase / yBase)) > 0.0001:
                yScaled = y * xBase / yBase
                x = (x + yScaled) / 2
                y = x * yBase / xBase
            self.setValues(x, y)

        if self.displayUnit == PERCENT:
            self._resetScale()

        self.xBase = xBase
        self.yBase = yBase

    def setBaseUnit(self, unit):
        self.baseUnit = unit
        self._resetScale()

    def setDisplayUnit(self, unit):
        self.displayUnit = unit
        self._resetScale()

    def linked(self):
        return self.link and self.link.isChecked()

    def setLinked(self, linked):
        if self.link:
            return self.link.setChecked(linked)
        else:
            assert not linked

class PreviewWidget(QGraphicsView):
    def __init__(self, parent=None):
        scene = QGraphicsScene()
        super(PreviewWidget, self).__init__(scene, parent)

        self.scene = scene
        self.inputPage = None
        self.outputSize = (0, 0)
        self.cropSize = (0, 0)
        self.cropOrig = (0, 0)
        self.pageSize = (0, 0)
        self.pageMargin = (0, 0)

        self.cropRectItem = None
        self.pageRectItems = []

        backgroundBrush = QBrush(Qt.gray)
        self.scene.setBackgroundBrush(backgroundBrush)

        self.cropPen = QPen()
        self.cropPen.setStyle(Qt.SolidLine)
        self.cropPen.setWidth(1)
        self.cropPen.setBrush(Qt.red)
        self.cropPen.setCapStyle(Qt.RoundCap)
        self.cropPen.setJoinStyle(Qt.RoundJoin)

        self.pagePen = QPen()
        self.pagePen.setStyle(Qt.SolidLine)
        self.pagePen.setWidth(1)
        self.pagePen.setBrush(Qt.gray)
        self.pagePen.setCapStyle(Qt.RoundCap)
        self.pagePen.setJoinStyle(Qt.RoundJoin)

    def _reload(self):
        self.scene.clear()
        self.image = None
        self.cropRectItem = None
        self.pageRectItems = []
        if not self.inputPage:
            return

        # We like 96 DPI
        preferredSize = (self.inputPage.getSize() *
                         96 * self.devicePixelRatio()) / 72
        self.image = self.inputPage.getQImage(preferredSize)
        self.pixmap = self.scene.addPixmap(QPixmap.fromImage(self.image))
        pageSize = self.inputPage.getSize()
        # Assume it scales the same in both directions
        assert (pageSize.width() * self.image.height() ==
                pageSize.height() * self.image.width())
        self.pixmap.setScale(pageSize.width() / self.image.width())
        self.setSceneRect(QRectF(QRect(QPoint(0, 0), pageSize)))
        self.setTransform(QTransform().scale(96 / 72, 96 / 72))

    def setInputPage(self, page):
        if self.inputPage != page:
            self.inputPage = page
            self._reload()
            self._updateRects()

    def _updateRects(self):
        if self.cropRectItem:
            self.scene.removeItem(self.cropRectItem)
        self.cropRectItem = None

        for r in self.pageRectItems:
            self.scene.removeItem(r)
        self.pageRectItems = []

        cropRect = QRectF(self.cropOrig[0], self.cropOrig[1],
                          self.cropSize[0], self.cropSize[1])
        self.cropRectItem = self.scene.addRect(cropRect, pen=self.cropPen,
                                               brush=QBrush(Qt.NoBrush))

        printSize = (self.pageSize[0] - 2 * self.pageMargin[0],
                     self.pageSize[1] - 2 * self.pageMargin[1])
        if printSize[0] == 0 or printSize[1] == 0:
            return

        numPagesX = math.ceil(self.outputSize[0] / printSize[0])
        numPagesY = math.ceil(self.outputSize[1] / printSize[1])

        if self.outputSize[0] == 0 or self.outputSize[1] == 0:
            return

        pageRectSize = (printSize[0] * self.cropSize[0] / self.outputSize[0],
                        printSize[1] * self.cropSize[1] / self.outputSize[1])

        for y in range(numPagesY):
            for x in range(numPagesX):
                pageRect = QRectF(self.cropOrig[0] + x * pageRectSize[0],
                                  self.cropOrig[1] + y * pageRectSize[1],
                                  pageRectSize[0],
                                  pageRectSize[1])
                rectItem = self.scene.addRect(pageRect, pen=self.pagePen,
                                              brush=QBrush(Qt.NoBrush))
                self.pageRectItems.append(rectItem)

    def setCropOrig(self, x, y):
        self.cropOrig = (x, y)
        self._updateRects()

    def setCropSize(self, width, height):
        self.cropSize = (width, height)
        self._updateRects()

    def setOutputSize(self, width, height):
        self.outputSize = (width, height)
        self._updateRects()

    def setPageSize(self, width, height):
        self.pageSize = (width, height)
        self._updateRects()

    def setPageMargin(self, width, height):
        self.pageMargin = (width, height)
        self._updateRects()


def loadPageLayout(settings, name, default):
    pageSize = settings.value(name + '/page-size', None)
    if not isinstance(pageSize, QSize):
        return default
    pageSize = QPageSize(pageSize)

    orientation = settings.value(name + '/orientation', None)
    try:
        orientation = int(orientation)
    except:
        return default

    margins = settings.value(name + '/margins', None)
    if not isinstance(margins, QRectF):
        return default
    margins = QMarginsF(margins.x(), margins.y(),
                        margins.width(), margins.height())

    units = settings.value(name + '/units', None)
    try:
        units = int(units)
    except:
        return default

    return QPageLayout(pageSize, orientation, margins, units)


def savePageLayout(settings, name, layout):
    settings.setValue(name + '/page-size', layout.pageSize().sizePoints())
    settings.setValue(name + '/orientation', layout.orientation())

    # Pretend the QMarginsF is a QRectF
    margins = layout.margins()
    margins = QRectF(margins.left(), margins.top(),
                     margins.right(), margins.bottom())
    settings.setValue(name + '/margins', margins)

    settings.setValue(name + '/units', layout.units())


class MainWindow(QMainWindow):
    def __init__(self, ctx, parent=None):
        super(MainWindow, self).__init__(parent)

        self.inputPDF = None
        self.inputPage = None
        self.inputPageNumber = 0

        self.openAction = QAction(QIcon.fromTheme('document-open'), '&Open')
        self.openAction.triggered.connect(self.openFileDialog)

        self.printAction = QAction(QIcon.fromTheme('document-print'), '&Print')
        self.printAction.triggered.connect(self.printDialog)

        self.quitAction = QAction(QIcon.fromTheme('application-exit'), '&Quit')
        self.quitAction.triggered.connect(self.close)

        self._setupMenus()

        hLayout = QHBoxLayout()

        # Preview widget
        self.preview = PreviewWidget()
        hLayout.addWidget(self.preview)

        # A parent widget to contain all the knobs
        formWidget = QWidget()
        formLayout = QVBoxLayout()
        formWidget.setLayout(formLayout)
        hLayout.addWidget(formWidget)

        # Page number spinner
        self.pageNumSpin = QSpinBox()
        self.pageNumSpin.setMinimum(1)
        self.pageNumSpin.setMaximum(1)
        self.pageNumSpin.setValue(self.inputPageNumber)
        self.pageNumSpin.valueChanged.connect(self.setPageNumber)
        pageNumBox = QGroupBox()
        pageNumBox.setTitle('Page Number')
        layout = QHBoxLayout()
        layout.addWidget(self.pageNumSpin)
        pageNumBox.setLayout(layout)
        formLayout.addWidget(pageNumBox)

        # Scale widget
        self.cropOrig = DimWidget(ctx, 'X', 'Y')
        self.cropOrig.setLinked(False)
        self.cropOrig.valueChanged.connect(self.preview.setCropOrig)
        self.cropDim = DimWidget(ctx, 'Width', 'Height')
        self.cropDim.setLinked(False)
        self.cropDim.valueChanged.connect(self.preview.setCropSize)
        self.cropUnits = UnitsComboBox()
        self.cropUnits.valueChanged.connect(self.cropOrig.setDisplayUnit)
        self.cropUnits.valueChanged.connect(self.cropDim.setDisplayUnit)
        cropBox = QGroupBox()
        cropBox.setTitle('Input Crop')
        layout = QVBoxLayout()
        layout.addWidget(self.cropOrig)
        layout.addWidget(self.cropDim)
        layout.addWidget(self.cropUnits)
        cropBox.setLayout(layout)
        formLayout.addWidget(cropBox)

        # Scale widget
        self.scale = DimWidget(ctx, 'X', 'Y')
        self.scale.setMaximums(MILE_IN_POINTS, MILE_IN_POINTS)
        self.cropDim.valueChanged.connect(self.scale.setBaseValues)
        self.preview.setOutputSize(*self.scale.values())
        self.scale.valueChanged.connect(self.preview.setOutputSize)
        self.scaleUnits = UnitsComboBox()
        self.scaleUnits.valueChanged.connect(self.scale.setDisplayUnit)
        scaleBox = QGroupBox()
        scaleBox.setTitle('Output Size')
        layout = QVBoxLayout()
        layout.addWidget(self.scale)
        layout.addWidget(self.scaleUnits)
        scaleBox.setLayout(layout)
        formLayout.addWidget(scaleBox)

        self.registrationMarks = QCheckBox('Registration Marks')
        self.registrationMarks.setChecked(True)
        formLayout.addWidget(self.registrationMarks)

        self.overDraw = QCheckBox('Over-draw into margin')
        self.overDraw.setChecked(False)
        formLayout.addWidget(self.overDraw)

        self.saveButton = QPushButton('Print')
        self.saveButton.setIcon(QIcon.fromTheme('document-print'))
        self.saveButton.clicked.connect(self.printDialog)
        formLayout.addWidget(self.saveButton)

        # A dummy padding widget
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        formLayout.addWidget(spacer)

        wid = QWidget()
        wid.setLayout(hLayout)
        self.setCentralWidget(wid)

        self.setWindowTitle('pdfXplode')

    def _setupMenus(self):
        menuBar = self.menuBar()
        fileMenu = menuBar.addMenu('&File')
        fileMenu.addAction(self.openAction)
        fileMenu.addAction(self.printAction)
        fileMenu.addSeparator()
        fileMenu.addAction(self.quitAction)

    def _updatePageSize(self):
        if self.inputPage is None:
            return

        size = self.inputPage.getSize()
        self.cropUnits.setAvailableUnits(self.inputPage.getAllowedUnits())
        self.cropOrig.setMaximums(size.width(), size.height())
        self.cropOrig.setBaseValues(size.width(), size.height())
        self.cropOrig.setValues(0, 0)
        self.cropOrig.setBaseUnit(self.inputPage.getNativeUnit())
        self.cropOrig.setDisplayUnit(self.cropUnits.value())
        self.cropDim.setMaximums(size.width(), size.height())
        self.cropDim.setBaseValues(size.width(), size.height())
        self.cropDim.setValues(size.width(), size.height())
        self.cropDim.setBaseUnit(self.inputPage.getNativeUnit())
        self.cropDim.setDisplayUnit(self.cropUnits.value())
        if self.inputPage.getNativeUnit() == POINTS:
            self.scaleUnits.setAvailableUnits([PERCENT, POINTS, INCHES])
        else:
            self.scaleUnits.setAvailableUnits([POINTS, INCHES])
        self.scale.setBaseValues(size.width(), size.height())
        self.scale.setValues(size.width(), size.height())
        self.scale.setDisplayUnit(self.scaleUnits.value())

    def setPageNumber(self, pageNumber):
        if self.inputPDF is None:
            return # Only PDFs have page numbers

        if self.inputPageNumber != pageNumber or self.inputPage is None:
            if self.inputPage is not None:
                self.inputPage.cleanup()
            self.inputPageNumber = pageNumber
            self.inputPage = self.inputPDF.getPage(pageNumber)
            self.preview.setInputPage(self.inputPage)
            self._updatePageSize()

    def loadPDF(self, fileName):
        if self.inputPDF:
            self.inputPDF.cleanup()
        self.inputPDF = InputPDFFile(fileName)
        self.inputPage = None
        self.pageNumSpin.setDisabled(False)
        self.pageNumSpin.setMaximum(self.inputPDF.getNumPages())
        self.setPageNumber(self.pageNumSpin.value())

    def loadImage(self, fileName):
        if self.inputPDF:
            self.inputPDF.cleanup()
        self.inputPDF = None
        self.inputPage = InputImage(fileName)
        self.pageNumSpin.setDisabled(True)
        self.preview.setInputPage(self.inputPage)
        self._updatePageSize()

    def openFileDialog(self):
        filters = 'PDF files (*.pdf);;Images (*.png *.jpg)'
        fname = QFileDialog.getOpenFileName(self, 'Open input file',
                                            filter=filters)
        if not fname or not fname[0]:
            return # Canceled

        ext = os.path.splitext(fname[0])[1].lower()
        if ext == '.pdf':
            self.loadPDF(fname[0])
        elif ext in ('.png', '.jpg'):
            self.loadImage(fname[0])
        else:
            raise RuntimeError("Unknown file extension")

    def printDialog(self):
        settings = QSettings()

        printer = QPrinter()
        printer.setColorMode(QPrinter.Color)

        defaultPageLayout = QPageLayout(QPageSize(QPageSize.Letter),
                                        QPageLayout.Portrait,
                                        QMarginsF(0.5, 0.5, 0.5, 0.5),
                                        QPageLayout.Inch)
        pageLayout = loadPageLayout(settings, 'output/page-layout',
                                    defaultPageLayout)
        printer.setPageLayout(pageLayout)

        cropRect = QRect(*self.cropOrig.values(), *self.cropDim.values())
        outSize = QSize(*self.scale.values())
        trim = not self.overDraw.isChecked()
        registrationMarks = self.registrationMarks.isChecked()

        def paintPreview(printer):
            printInputImage(printer, self.inputPage, cropRect,
                            outSize, trim, registrationMarks)

        preview = QPrintPreviewDialog(printer)
        preview.paintRequested.connect(paintPreview)
        if preview.exec() == QDialog.Accepted:
            savePageLayout(settings, "output/page-layout", printer.pageLayout())


if __name__ == '__main__':
    QCoreApplication.setOrganizationName("jlekstrand.net")
    QCoreApplication.setOrganizationDomain("jlekstrand.net")
    QCoreApplication.setApplicationName("pdfXtract")

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

    ctx = ApplicationContext()

    menuBar = QMenuBar();
    openAct = QAction('&Open')
    menuBar.addAction(openAct)

    window = MainWindow(ctx)
    window.show()
    sys.exit(ctx.app.exec_())
